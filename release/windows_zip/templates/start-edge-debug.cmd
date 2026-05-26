@echo off
setlocal
cd /d "%~dp0"

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" -DebugMode
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo FlyPrint Edge debug startup failed with exit code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
