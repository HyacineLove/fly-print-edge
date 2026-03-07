# FlyPrint Edge 部署手册 (Windows)

本手册适用于在纯净 Windows 环境（仅预装 Python）上部署 FlyPrint Edge 客户端。本项目已实现**零环境变量依赖**，所有配置均通过 `config.json` 管理。

## 1. 环境准备

### 1.1 系统要求
- 操作系统: Windows 10 或 Windows 11 (64位)
- 网络: 需通过以太网或 Wi-Fi 连接到局域网，且能访问云端服务器 (默认 `192.168.50.2`)

### 1.2 软件依赖
- **Python 3.10+**: 必须安装。
  - 下载地址: [Python官网](https://www.python.org/downloads/windows/)
  - **重要**: 安装时务必勾选 **"Add Python to PATH"** (将 Python 添加到环境变量)。

## 2. 安装步骤

### 2.1 获取代码
将 `fly-print-edge` 文件夹复制到目标机器的任意位置（例如桌面）。

### 2.2 初始化环境
1. 打开文件夹，在空白处按住 `Shift` 键并右击，选择 **"在此处打开 Powershell 窗口"** (或 "在终端中打开")。

2. (可选) 创建虚拟环境以隔离依赖：
   ```powershell
   python -m venv venv
   ```

3. 激活虚拟环境：
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   *注意：如果提示禁止执行脚本，请先运行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` 允许脚本执行。*

4. 安装依赖库：
   ```powershell
   pip install -r requirements.txt
   ```
   *提示：如果下载速度慢，可使用国内镜像：*
   ```powershell
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```

## 3. 配置说明

所有配置均位于 `config.json` 文件中。请使用记事本或代码编辑器打开并修改。

### 3.1 核心配置 (config.json)

```json
{
    "network": {
        "bind_address": "0.0.0.0",  // 监听地址，0.0.0.0 允许局域网访问
        "port": 7860               // 服务端口
    },
    "cloud": {
        "enabled": true,           // 是否启用云端连接
        "base_url": "http://192.168.50.2",        // 云端服务器地址 (注意是 http)
        "auth_url": "http://192.168.50.2/auth/token", // 认证地址
        "client_id": "fly-print-edge",            // OAuth2 客户端ID
        "client_secret": "fly-print-edge-secret", // OAuth2 客户端密钥 (必须与云端数据库一致)
        "node_name": "Edge-Office-01",            // 本节点名称 (自定义)
        "location": "办公室前台",                  // 节点位置描述
        "auto_register": true                     // 是否自动注册节点
    },
    "settings": {
        "admin_api_key": "admin_secret_key_123"   // 本地管理后台 API 密钥 (用于安全验证)
    }
}
```

### 3.2 常见修改项
- **云端地址**: 修改 `cloud.base_url` 和 `auth_url` 为实际的云端服务器 IP。
- **客户端密钥**: 确保 `cloud.client_secret` 与云端数据库中配置的一致。
- **节点信息**: 修改 `node_name` 和 `location` 以区分不同位置的打印机。

## 4. 启动服务

在 PowerShell 窗口中运行：

```powershell
python main.py
```

### 启动成功标志
控制台输出如下信息即表示启动成功：
- `🚀 启动服务: 127.0.0.1:7860`
- `✅ 云端服务启动成功`
- `✅ WebSocket客户端启动成功`

## 5. 验证与使用

1. **本地访问**: 打开浏览器访问 `http://localhost:7860`，应能看到 Kiosk 界面。
2. **管理后台**: 访问 `http://localhost:7860/admin`，进入设备管理界面。
3. **云端连接**: 在云端管理后台，应能看到新上线的 Edge 节点。

## 6. 常见问题排查

### Q1: 提示 "SSL: CERTIFICATE_VERIFY_FAILED"?
- **原因**: URL 配置错误
- **解决**: 检查 `config.json` 中的 URL 是否误写为 `https://`。本项目已全面迁移至 HTTP，请使用 `http://`。

### Q2: 无法连接到云端服务器?
- **检查网络**: `ping 192.168.50.2`（替换为你的服务器IP）
- **检查端口**: `telnet 192.168.50.2 80`
- **检查防火墙**: 确保服务器防火墙开放 80 端口
- **检查密钥**: 确保 `client_secret` 与云端 `.env` 配置一致

### Q3: 打印机检测不到?
- **Windows**: 确保打印机已正确安装并在"设备和打印机"中可见
- **网络打印机**: 确保打印机与 Edge 节点在同一网络
- **驱动程序**: 安装打印机官方驱动

### Q4: 文件上传后无法打印?
- **检查日志**: 查看控制台输出的错误信息
- **文件格式**: 确认文件格式支持（PDF, Word, Excel, 图片等）
- **LibreOffice**: 确保 `portable/LibreOfficePortablePrevious` 存在（用于 Office 文档转换）

## 7. 开机自启动（Windows）

### 方法1: 任务计划程序
1. 打开"任务计划程序"
2. 创建基本任务
3. 触发器: "计算机启动时"
4. 操作: "启动程序"
   - 程序: `C:\path\to\python.exe`
   - 参数: `C:\path\to\fly-print-edge\main.py`
   - 起始位置: `C:\path\to\fly-print-edge`

### 方法2: 使用启动脚本
创建 `start.bat`:
```batch
@echo off
cd /d %~dp0
call venv\Scripts\activate.bat
python main.py
pause
```

将快捷方式放到启动文件夹：
`C:\Users\<用户名>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`

## 8. 更新日志

### v0.2.0 (2026-03-04)
- **安全增强**: Token 撤销机制
  - 刷新二维码时自动使旧 Token 失效
  - 防止旧上传链接被滥用
- **性能优化**: QR 码请求超时延长至 10 秒
- **UI 优化**: 
  - 移动端响应式布局优化
  - 桌面端预览区域高度调整（900px）

### v0.1.0
- 初始版本发布

## 9. 技术支持

如遇问题，请查看：
- **README.md**: 项目说明
- **控制台日志**: 运行时详细输出
- **云端日志**: 在云端管理后台查看节点日志

- **Q: 无法连接云端 (Connection refused)?**
  - A: 检查云端服务器 IP 是否正确，以及云端防火墙是否放行了 80 端口。

- **Q: PowerShell 提示 "无法加载文件...因为在此系统上禁止运行脚本"?**
  - A: 运行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` 解除限制。
