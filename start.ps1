# Edge Service Startup Script
# Usage: .\start.ps1 [-Setup] [-Clean]

param(
    [switch]$Setup,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$VenvDir = "venv"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  FlyPrint Edge Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Clean virtual environment
if ($Clean) {
    Write-Host "Cleaning virtual environment..." -ForegroundColor Yellow
    if (Test-Path $VenvDir) {
        Remove-Item -Path $VenvDir -Recurse -Force
        Write-Host "Done: Virtual environment cleaned" -ForegroundColor Green
    }
    $Setup = $true
}

# Check if virtual environment exists
if (-not (Test-Path $VenvDir) -or $Setup) {
    Write-Host "[1/3] Creating virtual environment..." -ForegroundColor Yellow
    
    # Check Python installation
    try {
        $pythonVersion = python --version 2>&1
        Write-Host "  Python Version: $pythonVersion" -ForegroundColor Gray
    }
    catch {
        Write-Host "Error: Python not found. Please install Python 3.8+" -ForegroundColor Red
        exit 1
    }
    
    # Create virtual environment
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "Done: Virtual environment created" -ForegroundColor Green
    
    Write-Host ""
    Write-Host "[2/3] Installing dependencies..." -ForegroundColor Yellow
    
    # Activate virtual environment and install dependencies
    & "venv\Scripts\Activate.ps1"
    
    # Upgrade pip
    Write-Host "  Upgrading pip..." -ForegroundColor Gray
    python -m pip install --upgrade pip -q
    
    # Install dependencies
    Write-Host "  Installing requirements.txt..." -ForegroundColor Gray
    pip install -r requirements.txt -q
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: Failed to install dependencies" -ForegroundColor Red
        exit 1
    }
    Write-Host "Done: Dependencies installed" -ForegroundColor Green
    
    Write-Host ""
    Write-Host "[3/3] Setup completed!" -ForegroundColor Green
    Write-Host ""
    
    if ($Setup) {
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  Setup Complete!" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Start Edge service with:" -ForegroundColor Yellow
        Write-Host "  .\start.ps1" -ForegroundColor White
        Write-Host ""
        exit 0
    }
}

# Check config file
if (-not (Test-Path "config.json")) {
    Write-Host "WARNING: config.json not found" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please configure Edge node first:" -ForegroundColor Yellow
    Write-Host "1. Login to Cloud Admin (http://localhost)" -ForegroundColor White
    Write-Host "2. Create OAuth2 Client" -ForegroundColor White
    Write-Host "3. Copy Client ID and Secret" -ForegroundColor White
    Write-Host "4. Update config.json with credentials" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to continue (may fail)"
}

# Start Edge service
Write-Host "Starting Edge service..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Virtual Env: $(Resolve-Path $VenvDir)" -ForegroundColor Gray
Write-Host "Working Dir: $(Get-Location)" -ForegroundColor Gray
Write-Host "Config File: $(if (Test-Path 'config.json') {'OK'} else {'MISSING'})" -ForegroundColor Gray
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Edge Service Running..." -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment and run
& "venv\Scripts\Activate.ps1"
python main.py