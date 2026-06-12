"""
AI Provider Chain — zero-cost inference
Priority order based on June 2026 free tier reality:
  1. Gemini Flash   — 1,500 req/day, 1M TPM  (best volume, use for bulk)
  2. Groq Llama 3.1 — 14,400 req/day, 6K TPM  (fastest, use for short tasks)
  3. OpenRouter     — 100 req/day             (fallback only)
  4. Ollama local   — unlimited               (last resort, needs local GPU/CPU)

Key corrections vs original design:
- Groq free tier: 1,000 RPD per model (NOT 14,400) for 70B.
  llama-3.1-8b-instant gets 14,400 RPD. Use 8B for content, 70B only for bounties.
- Gemini 2.5 Pro: 50 RPD free tier only. Use Flash (1,500 RPD) for everything.
- Google may use your free-tier prompts for training. Avoid sensitive data.
"""

import os
import time
import json
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


def call_gemini(prompt: str, system: str = "", max_tokens: int = 2000) -> Optional[str]:
    """Gemini 2.5 Flash — 1,500 RPD, 1M TPM, best for bulk content generation."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            "gemini-2.5-flash",
            system_instruction=system if system else None,
        )
        resp = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
        )
        return resp.text
    except Exception as e:
        logger.warning(f"Gemini failed: {e}")
        return None


def call_groq(prompt: str, system: str = "", model: str = "llama-3.1-8b-instant", max_tokens: int = 2000) -> Optional[str]:
    """
    Groq — fastest inference (sub-200ms). Free tier per model:
      llama-3.1-8b-instant : 14,400 RPD  ← use for content writing
      llama-3.3-70b-versatile: 1,000 RPD  ← use for code/reasoning
    """
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning(f"Groq ({model}) failed: {e}")
        return None


def call_openrouter(prompt: str, system: str = "", max_tokens: int = 1500) -> Optional[str]:
    """OpenRouter free tier — 100 RPD. Reserve for fallback only."""
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={"model": "openrouter/free", "messages": messages, "max_tokens": max_tokens},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"OpenRouter failed: {e}")
        return None


def call_ollama(prompt: str, system: str = "", model: str = "llama3.1:8b") -> Optional[str]:
    """Ollama local — unlimited but needs local hardware. Last resort."""
    try:
        import requests
        payload = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        r = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["response"]
    except Exception as e:
        logger.warning(f"Ollama failed: {e}")
        return None


def ai(
    prompt: str,
    system: str = "",
    task: str = "content",  # "content" | "code" | "reason"
    max_tokens: int = 2000,
) -> str:
    """
    Smart dispatch based on task type and real free tier limits.
    - content: Gemini first (1,500 RPD) → Groq 8B (14,400 RPD)
    - code/reason: Groq 70B (1,000 RPD) → Gemini → OpenRouter
    Always falls back gracefully. Never raises.
    """
    if task == "content":
        chain = [
            lambda: call_gemini(prompt, system, max_tokens),
            lambda: call_groq(prompt, system, "llama-3.1-8b-instant", max_tokens),
            lambda: call_openrouter(prompt, system, max_tokens),
            lambda: call_ollama(prompt, system),
        ]
    else:  # code or reasoning
        chain = [
            lambda: call_groq(prompt, system, "llama-3.3-70b-versatile", max_tokens),
            lambda: call_gemini(prompt, system, max_tokens),
            lambda: call_openrouter(prompt, system, max_tokens),
            lambda: call_ollama(prompt, system, "codellama:13b"),
        ]

    for fn in chain:
        result = fn()
        if result and len(result.strip()) > 10:
            return result.strip()
        time.sleep(0.5)

    return "ERROR: All AI providers exhausted. Check API keys and rate limits."
