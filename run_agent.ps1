<# 
.SYNOPSIS
    ZeroAgent — Autonomous Earning System Runner
.DESCRIPTION
    Runs the ZeroAgent autonomous earning agent locally with .env configuration.
    Zero investment, runs on free tiers only.
#>

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "ZeroAgent - Autonomous Earning System" -ForegroundColor Green
Write-Host "Zero Investment | Free Tiers Only" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Error "ERROR: .env file not found!"
    Write-Host "Please ensure .env exists with your API keys" -ForegroundColor Yellow
    exit 1
}

Write-Host "Loading environment from .env..." -ForegroundColor Green
Write-Host ""

# Load .env manually for visibility
$envContent = Get-Content .env -Raw
Write-Host "Environment loaded:" -ForegroundColor Cyan
$envContent -split "`n" | Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object {
    if ($_ -match "^(.+?)=(.+)$") {
        $key = $matches[1].Trim()
        $val = $matches[2].Trim()
        if ($val.Length -gt 20) { $val = $val.Substring(0, 20) + "..." }
        Write-Host "  $key = $val"
    }
}
Write-Host ""

# Run the agent
Write-Host "Starting ZeroAgent cycle..." -ForegroundColor Green
Write-Host ""

$args = $args -join " "
python main.py $args

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Agent cycle complete" -ForegroundColor Green
Write-Host "Check logs/ folder for details" -ForegroundColor Yellow
Write-Host "Check memory/agent.db for persistent state" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

Read-Host "Press Enter to exit"