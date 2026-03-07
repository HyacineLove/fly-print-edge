@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==========================================
echo    Fly-Print Edge 清理工具
echo ==========================================
echo.

:: 删除桌面快捷方式
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Fly-Print 管理界面.url"
if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [已删除] 桌面快捷方式
) else (
    echo [跳过] 未找到桌面快捷方式
)

:: 可选：删除虚拟环境
echo.
if exist "venv" (
    set /p DEL_VENV="是否删除 venv 虚拟环境目录？(Y/N): "
    if /i "!DEL_VENV!"=="Y" (
        rd /s /q "venv"
        echo [已删除] venv 目录
    ) else (
        echo [跳过] 保留 venv 目录
    )
)

:: 可选：删除临时文件
if exist "temp" (
    set /p DEL_TEMP="是否删除 temp 临时文件目录？(Y/N): "
    if /i "!DEL_TEMP!"=="Y" (
        rd /s /q "temp"
        echo [已删除] temp 目录
    ) else (
        echo [跳过] 保留 temp 目录
    )
)

echo.
echo ==========================================
echo    清理完成
echo ==========================================
echo.
pause
