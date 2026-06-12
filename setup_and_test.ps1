<# 
.SYNOPSIS
    ZeroAgent — Complete Setup and Test
.DESCRIPTION
    Installs dependencies, initializes database, and runs test cycles.
#>

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "ZeroAgent - Complete Setup & Test" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install dependencies
Write-Host "Step 1: Installing Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install dependencies"
    exit 1
}
Write-Host "Dependencies installed successfully!" -ForegroundColor Green
Write-Host ""

# Step 2: Initialize database
Write-Host "Step 2: Initializing database..." -ForegroundColor Yellow
python main.py --init
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to initialize database"
    exit 1
}
Write-Host "Database initialized!" -ForegroundColor Green
Write-Host ""

# Step 3: Test health check
Write-Host "Step 3: Testing health check..." -ForegroundColor Yellow
python -c "
import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.env'))

# Test AI providers
from agent.ai_chain import call_gemini, call_groq, call_openrouter

# Quick test
print('Testing Gemini...')
result = call_gemini('Say hello in one sentence')
print(f'Gemini: {result[:50]}...' if result else 'Gemini: FAILED')

print('Testing Groq...')
result = call_groq('Say hello in one sentence')
print(f'Groq: {result[:50]}...' if result else 'Groq: FAILED')

print('Testing OpenRouter...')
result = call_openrouter('Say hello in one sentence')
print(f'OpenRouter: {result[:50]}...' if result else 'OpenRouter: FAILED')
"
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some AI providers failed - check API keys in .env"
}
Write-Host ""

# Step 4: Test content_affiliate (dry run)
Write-Host "Step 4: Testing content_affiliate vehicle (dry run)..." -ForegroundColor Yellow
python main.py --vehicle content_affiliate --dry-run
Write-Host ""

# Step 5: Test bounty_hunting (dry run)
Write-Host "Step 5: Testing bounty_hunting vehicle (dry run)..." -ForegroundColor Yellow
python main.py --vehicle bounty_hunting --dry-run
Write-Host ""

# Step 6: Run full cycle (dry run)
Write-Host "Step 6: Running full autonomous cycle (dry run)..." -ForegroundColor Yellow
python main.py --dry-run
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Setup & Test Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Create a PUBLIC GitHub repo and push this code"
Write-Host "2. Add these secrets to GitHub Actions:"
Write-Host "   - GEMINI_API_KEY"
Write-Host "   - GROQ_API_KEY"
Write-Host "   - OPENROUTER_API_KEY"
Write-Host "   - DEVTO_API_KEY"
Write-Host "3. Enable GitHub Actions in the repo"
Write-Host "4. The agent will run automatically every 30 minutes"
Write-Host ""
Write-Host "To run locally: .\run_agent.ps1" -ForegroundColor Cyan
Write-Host "To run real cycle: python main.py" -ForegroundColor Cyan
Read-Host "Press Enter to exit"