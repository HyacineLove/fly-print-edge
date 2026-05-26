param(
    [switch]$DebugMode
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PackageRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $PackageRoot "app"
$LogsDir = Join-Path $PackageRoot "logs"
$TempDir = Join-Path $PackageRoot "temp"
$VenvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
$MainFile = Join-Path $AppDir "main.py"
$ConfigPath = Join-Path $AppDir "config.json"
$ServiceLogPath = Join-Path $LogsDir "edge-service.log"
$ServiceErrorLogPath = Join-Path $LogsDir "edge-service.error.log"

if (-not (Test-Path -LiteralPath $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $TempDir)) {
    New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
}

$BindAddress = "127.0.0.1"
$Port = 7860

if (Test-Path -LiteralPath $ConfigPath) {
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
        if ($config.network.bind_address) {
            $BindAddress = [string]$config.network.bind_address
        }
        if ($config.network.port) {
            $Port = [int]$config.network.port
        }
    }
    catch {
        Write-Warning "Failed to parse app\\config.json. Falling back to default bind address and port."
    }
}

if ($DebugMode) {
    $env:FLYPRINT_LOG_LEVEL = "DEBUG"
    $env:FLYPRINT_DEBUG_LOGGING = "true"
}

Write-Host "[FlyPrint] Working directory: $AppDir" -ForegroundColor Cyan
Write-Host "[FlyPrint] Service URL: http://${BindAddress}:$Port" -ForegroundColor Cyan
Write-Host "[FlyPrint] Runtime logs: $ServiceLogPath ; $ServiceErrorLogPath" -ForegroundColor Cyan

Push-Location $AppDir
try {
    $process = Start-Process `
        -FilePath $VenvPython `
        -ArgumentList @($MainFile) `
        -WorkingDirectory $AppDir `
        -RedirectStandardOutput $ServiceLogPath `
        -RedirectStandardError $ServiceErrorLogPath `
        -NoNewWindow `
        -PassThru `
        -Wait
    exit $process.ExitCode
}
finally {
    Pop-Location
}
