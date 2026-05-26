param(
    [switch]$DebugMode,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PackageRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $PackageRoot "app"
$LogsDir = Join-Path $PackageRoot "logs"
$TempDir = Join-Path $PackageRoot "temp"
$VenvDir = Join-Path $AppDir ".venv"
$RequirementsFile = Join-Path $AppDir "requirements.txt"
$RequirementsStamp = Join-Path $AppDir ".requirements.sha256"
$LaunchScript = Join-Path $PSScriptRoot "launch.ps1"
$ConfigExamplePath = Join-Path $AppDir "config.example.json"
$ConfigPath = Join-Path $AppDir "config.json"
$BootstrapLogPath = Join-Path $LogsDir "bootstrap.log"

function Write-Step {
    param([string]$Message)
    Write-Host "[FlyPrint] $Message" -ForegroundColor Cyan
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Test-PythonLauncher {
    param(
        [string]$Command,
        [string[]]$PrefixArgs = @()
    )
    try {
        & $Command @PrefixArgs "--version" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-PythonLauncher {
    if (Test-PythonLauncher -Command "py" -PrefixArgs @("-3")) {
        return @{
            Command = "py"
            PrefixArgs = @("-3")
        }
    }

    if (Test-PythonLauncher -Command "python") {
        return @{
            Command = "python"
            PrefixArgs = @()
        }
    }

    throw "Python 3 launcher was not found. Install Python and make sure either 'py -3' or 'python' works in cmd."
}

Ensure-Directory -Path $LogsDir
Ensure-Directory -Path $TempDir

Start-Transcript -Path $BootstrapLogPath -Append | Out-Null

try {
    $pythonLauncher = Get-PythonLauncher

    if ($Reinstall -and (Test-Path -LiteralPath $VenvDir)) {
        Write-Step "Removing existing virtual environment"
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath $VenvDir)) {
        Write-Step "Creating local virtual environment"
        & $pythonLauncher.Command @($pythonLauncher.PrefixArgs + @("-m", "venv", $VenvDir))
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create virtual environment at $VenvDir"
        }
    }

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Virtual environment python executable is missing: $VenvPython"
    }

    $requirementsHash = (Get-FileHash -LiteralPath $RequirementsFile -Algorithm SHA256).Hash
    $savedHash = ""
    if (Test-Path -LiteralPath $RequirementsStamp) {
        $savedHash = (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim()
    }

    if ($Reinstall -or ($savedHash -ne $requirementsHash)) {
        Write-Step "Installing Python dependencies"
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to upgrade pip inside $VenvDir"
        }

        & $VenvPython -m pip install -r $RequirementsFile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install dependencies from $RequirementsFile"
        }

        Set-Content -LiteralPath $RequirementsStamp -Value $requirementsHash -Encoding ASCII
    }
    else {
        Write-Step "Reusing existing virtual environment"
    }

    if ((-not (Test-Path -LiteralPath $ConfigPath)) -and (Test-Path -LiteralPath $ConfigExamplePath)) {
        Copy-Item -LiteralPath $ConfigExamplePath -Destination $ConfigPath
        Write-Warning "Created app\\config.json from config.example.json. Update cloud and printer settings before production use."
    }

    if ($DebugMode) {
        & $LaunchScript -DebugMode
    }
    else {
        & $LaunchScript
    }
    exit $LASTEXITCODE
}
finally {
    Stop-Transcript | Out-Null
}
