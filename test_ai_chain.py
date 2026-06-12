import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))

from agent.ai_chain import call_gemini, call_groq, call_openrouter

print('Testing call_gemini...')
result = call_gemini('Say hello in one sentence')
if result:
    print(f'call_gemini Success: {result[:100]}...')
else:
    print('call_gemini: FAILED')

print('Testing call_groq...')
result = call_groq('Say hello in one sentence')
if result:
    print(f'call_groq Success: {result[:100]}...')
else:
    print('call_groq: FAILED')

print('Testing call_openrouter...')
result = call_openrouter('Say hello in one sentence')
if result:
    print(f'call_openrouter Success: {result[:100]}...')
else:
    print('call_openrouter: FAILED')