import os
import google.generativeai as genai
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path('.env'))

api_key = os.environ.get("GEMINI_API_KEY")
print(f"API Key loaded: {api_key[:20]}..." if api_key else "NO KEY")

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content("Say hello in one sentence")
    print(f"Success: {resp.text}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")