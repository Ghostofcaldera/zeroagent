@echo off
REM ZeroAgent — Run Script
REM Runs the autonomous earning agent locally

echo ==========================================
echo ZeroAgent - Autonomous Earning System
echo Zero Investment | Free Tiers Only
echo ==========================================
echo.

REM Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    echo Please ensure .env exists with your API keys
    pause
    exit /b 1
)

echo Loading environment from .env...
echo.

REM Run the agent
echo Starting ZeroAgent cycle...
python main.py %*

echo.
echo ==========================================
echo Agent cycle complete
echo Check logs/ folder for details
echo Check memory/agent.db for persistent state
echo ==========================================
pause