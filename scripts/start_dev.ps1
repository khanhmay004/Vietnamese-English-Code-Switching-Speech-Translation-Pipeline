# Vietnamese-English Code-Switching Speech Translation Pipeline - Startup Script
# Run this to start all services for development

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Speech Translation Pipeline - Dev Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Check Python virtual environment
if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "[!] Virtual environment not found. Creating..." -ForegroundColor Yellow
    python -m venv .venv
}

# Activate venv
Write-Host "[1/5] Activating virtual environment..." -ForegroundColor Green
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
Write-Host "[2/5] Installing Python dependencies..." -ForegroundColor Green
pip install -r requirements.txt -q

# Initialize database
Write-Host "[3/5] Initializing database..." -ForegroundColor Green
python scripts/init_db.py

# Check if frontend dependencies are installed
if (-not (Test-Path ".\frontend\node_modules")) {
    Write-Host "[4/5] Installing frontend dependencies..." -ForegroundColor Green
    Set-Location frontend
    npm install
    Set-Location ..
} else {
    Write-Host "[4/5] Frontend dependencies already installed" -ForegroundColor Green
}

Write-Host "[5/5] Starting services..." -ForegroundColor Green
Write-Host ""
Write-Host "To start the backend:  uvicorn backend.main:app --reload --port 8000" -ForegroundColor Yellow
Write-Host "To start the frontend: cd frontend && npm run dev" -ForegroundColor Yellow
Write-Host ""
Write-Host "API Docs:     http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "Frontend:     http://localhost:5173" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
