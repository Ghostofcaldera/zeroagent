import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))

from agent.ai_chain import call_gemini, call_groq, call_openrouter

print('Testing Gemini...')
result = call_gemini('Say hello in one sentence')
if result:
    print(f'Gemini: {result[:100]}...')
else:
    print('Gemini: FAILED')

print('Testing Groq...')
result = call_groq('Say hello in one sentence')
if result:
    print(f'Groq: {result[:100]}...')
else:
    print('Groq: FAILED')

print('Testing OpenRouter...')
result = call_openrouter('Say hello in one sentence')
if result:
    print(f'OpenRouter: {result[:100]}...')
else:
    print('OpenRouter: FAILED')