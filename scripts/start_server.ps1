# Vietnamese-English Code-Switching Speech Translation Pipeline - Server Startup Script
# Starts all services: PostgreSQL check, FastAPI, Frontend, Gemini Worker
# Run from project root: .\scripts\start_server.ps1

param(
    [switch]$SkipWorker  # Optional: skip starting the Gemini worker
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Speech Translation Pipeline - Server Startup" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------------------
# 1. Check PostgreSQL Service
# -----------------------------------------------------------------------------
Write-Host "[1/6] Checking PostgreSQL service..." -ForegroundColor Yellow
$pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
if ($pgService) {
    if ($pgService.Status -ne "Running") {
        Write-Host "      Starting PostgreSQL..." -ForegroundColor Yellow
        Start-Service $pgService.Name
        Start-Sleep -Seconds 2
    }
    Write-Host "      PostgreSQL is running" -ForegroundColor Green
} else {
    Write-Host "      WARNING: PostgreSQL service not found. Assuming manual startup." -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# 2. Check/Create Virtual Environment
# -----------------------------------------------------------------------------
Write-Host "[2/6] Checking virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "      Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}
Write-Host "      Virtual environment ready" -ForegroundColor Green

# Activate venv for this session
. .\.venv\Scripts\Activate.ps1

# -----------------------------------------------------------------------------
# 3. Install Dependencies (if needed)
# -----------------------------------------------------------------------------
Write-Host "[3/6] Checking dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet 2>$null
Write-Host "      Python dependencies ready" -ForegroundColor Green

# Check frontend node_modules
if (-not (Test-Path ".\frontend\node_modules")) {
    Write-Host "      Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location frontend
    npm install --silent 2>$null
    Pop-Location
}
Write-Host "      Frontend dependencies ready" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 4. Initialize Database
# -----------------------------------------------------------------------------
Write-Host "[4/6] Initializing database..." -ForegroundColor Yellow
python scripts/init_db.py 2>$null
Write-Host "      Database ready" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 5. Get Tailscale IP (if available)
# -----------------------------------------------------------------------------
Write-Host "[5/6] Detecting network..." -ForegroundColor Yellow
$TailscaleIP = $null
try {
    $TailscaleIP = (tailscale ip -4 2>$null) | Select-Object -First 1
    if ($TailscaleIP) {
        Write-Host "      Tailscale IP: $TailscaleIP" -ForegroundColor Green
    }
} catch {
    Write-Host "      Tailscale not detected (using localhost only)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# 6. Start Services in Separate Windows
# -----------------------------------------------------------------------------
Write-Host "[6/6] Starting services..." -ForegroundColor Yellow
Write-Host ""

# Start FastAPI Backend
$backendCmd = "cd '$ProjectRoot'; .\`.venv\Scripts\Activate.ps1; uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Normal
Write-Host "      [STARTED] Backend on port 8000" -ForegroundColor Green

Start-Sleep -Seconds 1

# Start Vite Frontend
$frontendCmd = "cd '$ProjectRoot\frontend'; npm run dev -- --host 0.0.0.0"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -WindowStyle Normal
Write-Host "      [STARTED] Frontend on port 5173" -ForegroundColor Green

Start-Sleep -Seconds 1

# Start Gemini Queue Worker (unless skipped)
if (-not $SkipWorker) {
    $workerCmd = "cd '$ProjectRoot'; .\`.venv\Scripts\Activate.ps1; python -m backend.processing.gemini_worker --queue"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $workerCmd -WindowStyle Normal
    Write-Host "      [STARTED] Gemini Queue Worker" -ForegroundColor Green
} else {
    Write-Host "      [SKIPPED] Gemini Queue Worker (use --queue flag manually)" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  All services started!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Local Access:" -ForegroundColor White
Write-Host "    Frontend:  http://localhost:5173" -ForegroundColor Cyan
Write-Host "    API Docs:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "    Health:    http://localhost:8000/health" -ForegroundColor Cyan

if ($TailscaleIP) {
    Write-Host ""
    Write-Host "  Remote Access (Tailscale):" -ForegroundColor White
    Write-Host "    Frontend:  http://${TailscaleIP}:5173" -ForegroundColor Green
    Write-Host "    API Docs:  http://${TailscaleIP}:8000/docs" -ForegroundColor Green
}

Write-Host ""
Write-Host "  To stop: Close the 3 PowerShell windows that opened" -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
