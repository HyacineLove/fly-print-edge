@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==========================================
echo    Fly-Print Edge 卸载程序
echo ==========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本
    pause
    exit /b 1
)

set "INSTALL_DIR=C:\FlyPrint"
set "NSSM_EXE=%INSTALL_DIR%\portable\nssm\nssm.exe"

:: 停止并删除服务
if exist "%NSSM_EXE%" (
    echo [1/3] 停止并删除服务...
    net stop FlyPrintEdge >nul 2>&1
    "%NSSM_EXE%" remove FlyPrintEdge confirm >nul 2>&1
    echo   - 服务已删除
)

:: 删除桌面快捷方式
echo [2/3] 删除快捷方式...
if exist "%USERPROFILE%\Desktop\Fly-Print 管理界面.url" (
    del "%USERPROFILE%\Desktop\Fly-Print 管理界面.url"
)

:: 删除安装目录
echo [3/3] 删除程序文件...
echo.
echo 警告：即将删除以下目录及其所有内容：
echo %INSTALL_DIR%
echo.
set /p CONFIRM="确认删除？(Y/N): "
if /i "!CONFIRM!"=="Y" (
    rd /s /q "%INSTALL_DIR%"
    echo   - 程序文件已删除
) else (
    echo   - 已取消删除
)

echo.
echo ==========================================
echo    卸载完成！
echo ==========================================
echo.
pause
