@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==========================================
echo    Fly-Print Edge 自助终端安装程序
echo ==========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本
    echo 右键点击 install.bat，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 设置安装目录
set "INSTALL_DIR=C:\FlyPrint"
set "PORTABLE_DIR=%INSTALL_DIR%\portable"
set "PYTHON_DIR=%PORTABLE_DIR%\python"
set "SUMATRA_DIR=%PORTABLE_DIR%\sumatra"

echo [1/8] 创建安装目录...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%PORTABLE_DIR%" mkdir "%PORTABLE_DIR%"

:: 复制程序文件
echo [2/8] 复制程序文件...
xcopy /E /I /Y "*.py" "%INSTALL_DIR%\" >nul
xcopy /E /I /Y "static" "%INSTALL_DIR%\static\" >nul
copy /Y "requirements.txt" "%INSTALL_DIR%\" >nul
copy /Y "config.json" "%INSTALL_DIR%\" >nul
copy /Y "uninstall.bat" "%INSTALL_DIR%\" >nul

:: 复制 portable 工具（如果存在）
echo [3/8] 检查 portable 工具...
if exist "portable\python" (
    echo   - 复制 Python portable...
    xcopy /E /I /Y "portable\python" "%PYTHON_DIR%\" >nul
)
if exist "portable\sumatra" (
    echo   - 复制 SumatraPDF portable...
    xcopy /E /I /Y "portable\sumatra" "%SUMATRA_DIR%\" >nul
)

:: 检测或使用 portable Python
echo [4/8] 配置 Python 环境...
set "PYTHON_EXE="
if exist "%PYTHON_DIR%\python.exe" (
    set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
    echo   - 使用 portable Python: %PYTHON_EXE%
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%i in ('where python') do (
            set "PYTHON_EXE=%%i"
            goto :found_python
        )
    )
    :found_python
    if "!PYTHON_EXE!"=="" (
        echo [错误] 未找到 Python，请安装 Python 3.8+ 或将 portable Python 放到 portable\python 目录
        pause
        exit /b 1
    )
    echo   - 使用系统 Python: !PYTHON_EXE!
)

:: 安装 Python 依赖
echo [5/8] 安装 Python 依赖...
cd /d "%INSTALL_DIR%"
"!PYTHON_EXE!" -m pip install --upgrade pip >nul 2>&1
"!PYTHON_EXE!" -m pip install -r requirements.txt >nul 2>&1
if !errorlevel! neq 0 (
    echo [警告] 部分依赖安装失败，可能需要手动安装
)

:: 更新 config.json
echo [6/8] 配置应用程序...
if exist "%SUMATRA_DIR%\SumatraPDF.exe" (
    echo   - 配置 SumatraPDF 路径...
    powershell -Command "(Get-Content '%INSTALL_DIR%\config.json') -replace '\"pdf_printer_path\": \"\"', '\"pdf_printer_path\": \"%SUMATRA_DIR:\=\\%\\\\SumatraPDF.exe\"' | Set-Content '%INSTALL_DIR%\config.json'"
)

:: 创建服务启动脚本
echo [7/8] 创建服务脚本...
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%INSTALL_DIR%"
echo "!PYTHON_EXE!" main.py
) > "%INSTALL_DIR%\start.bat"

:: 注册为 Windows 服务（使用 NSSM）
echo [8/8] 配置开机自启动...
set "NSSM_EXE=%PORTABLE_DIR%\nssm\nssm.exe"
if exist "%NSSM_EXE%" (
    echo   - 使用 NSSM 注册为 Windows 服务...
    "%NSSM_EXE%" install FlyPrintEdge "%INSTALL_DIR%\start.bat" >nul 2>&1
    "%NSSM_EXE%" set FlyPrintEdge AppDirectory "%INSTALL_DIR%" >nul 2>&1
    "%NSSM_EXE%" set FlyPrintEdge DisplayName "Fly-Print Edge Service" >nul 2>&1
    "%NSSM_EXE%" set FlyPrintEdge Description "自助终端打印服务" >nul 2>&1
    "%NSSM_EXE%" set FlyPrintEdge Start SERVICE_AUTO_START >nul 2>&1
    echo   - 服务已注册，将在系统启动时自动运行
) else (
    echo   - NSSM 未找到，跳过服务注册
    echo   - 提示：将 nssm.exe 放到 portable\nssm 目录可启用开机自启动
)

:: 创建桌面快捷方式
echo.
echo [可选] 创建管理界面快捷方式...
set /p CREATE_SHORTCUT="是否创建桌面快捷方式？(Y/N): "
if /i "!CREATE_SHORTCUT!"=="Y" (
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\Fly-Print 管理界面.url'); $s.TargetPath = 'http://localhost:7860/admin.html'; $s.Save()"
    echo   - 快捷方式已创建到桌面
)

echo.
echo ==========================================
echo    安装完成！
echo ==========================================
echo.
echo 安装位置: %INSTALL_DIR%
echo.
echo 下一步操作：
if exist "%NSSM_EXE%" (
    echo   1. 启动服务: net start FlyPrintEdge
    echo   2. 访问管理界面: http://localhost:7860/admin.html
    echo   3. 停止服务: net stop FlyPrintEdge
    echo   4. 卸载程序: 运行 %INSTALL_DIR%\uninstall.bat
) else (
    echo   1. 手动启动: 双击 %INSTALL_DIR%\start.bat
    echo   2. 访问管理界面: http://localhost:7860/admin.html
    echo   3. 卸载程序: 运行 %INSTALL_DIR%\uninstall.bat
)
echo.
pause
