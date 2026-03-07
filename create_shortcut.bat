@echo off
chcp 65001 >nul

echo ==========================================
echo    Fly-Print Edge 创建桌面快捷方式
echo ==========================================
echo.

set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Fly-Print 管理界面.url"

if exist "%SHORTCUT_PATH%" (
    echo 桌面快捷方式已存在，将覆盖。
    echo.
)

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'http://localhost:7860/admin.html'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo 快捷方式已创建到桌面：Fly-Print 管理界面
    echo 目标地址：http://localhost:7860/admin.html
) else (
    echo [错误] 快捷方式创建失败
)

echo.
pause
