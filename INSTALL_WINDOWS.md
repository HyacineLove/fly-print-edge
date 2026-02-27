# Fly-Print Edge Windows 安装指南

## 📦 安装包准备

### 推荐方式：携带 Portable 工具的完整安装包

为了在自助终端上快速部署，推荐准备一个包含所有 portable 工具的安装包，目录结构如下：

```
fly-print-edge/
├── *.py                    # Python 源代码
├── static/                 # 静态资源
├── requirements.txt        # Python 依赖
├── config.json            # 配置文件
├── install.bat            # 安装脚本
├── uninstall.bat          # 卸载脚本
└── portable/              # portable 工具目录（可选）
    ├── python/            # Python portable 版本
    │   ├── python.exe
    │   ├── Scripts/
    │   └── Lib/
    ├── sumatra/           # SumatraPDF portable
    │   └── SumatraPDF.exe
    └── nssm/              # NSSM 服务管理工具
        └── nssm.exe
```

---

## 🔧 Portable 工具下载

### 1. Python Portable（必需）
- **下载地址**：https://www.python.org/downloads/windows/
- **推荐版本**：Python 3.11+ embeddable package
- **解压位置**：`portable/python/`
- **说明**：如果目标机器已安装 Python，可跳过

### 2. SumatraPDF Portable（推荐）
- **下载地址**：https://www.sumatrapdfreader.org/download-free-pdf-viewer
- **选择**：Portable version (ZIP)
- **解压位置**：`portable/sumatra/`
- **说明**：用于高速 PDF 打印，安装脚本会自动配置到 config.json

### 3. NSSM（推荐）
- **下载地址**：https://nssm.cc/download
- **解压位置**：`portable/nssm/`（只需要 nssm.exe）
- **说明**：用于将程序注册为 Windows 服务，实现开机自启动

---

## 🚀 安装步骤

### 方法 1：使用安装脚本（推荐）

1. **以管理员身份运行 `install.bat`**
   - 右键点击 `install.bat` → 选择"以管理员身份运行"

2. **安装脚本会自动完成以下操作**：
   - 创建安装目录 `C:\FlyPrint`
   - 复制程序文件和 portable 工具
   - 检测或使用 portable Python
   - 安装 Python 依赖
   - 配置 SumatraPDF 路径
   - 注册为 Windows 服务（如果提供了 NSSM）
   - 创建桌面快捷方式（可选）

3. **启动服务**：
   ```cmd
   net start FlyPrintEdge
   ```

4. **访问管理界面**：
   - 打开浏览器访问 `http://localhost:7860/admin.html`

---

### 方法 2：手动安装

如果不使用安装脚本，可以手动安装：

1. **复制文件到目标位置**：
   ```cmd
   xcopy /E /I fly-print-edge C:\FlyPrint
   ```

2. **安装 Python 依赖**：
   ```cmd
   cd C:\FlyPrint
   python -m pip install -r requirements.txt
   ```

3. **配置 config.json**：
   - 修改 `pdf_printer_path` 为 SumatraPDF 的路径（如果使用）

4. **启动程序**：
   ```cmd
   python main.py
   ```

---

## 🎯 开机自启动配置

### 使用 NSSM（推荐）

如果安装包中包含 NSSM，安装脚本会自动注册服务。手动注册命令：

```cmd
:: 注册服务
nssm install FlyPrintEdge "C:\FlyPrint\start.bat"
nssm set FlyPrintEdge AppDirectory "C:\FlyPrint"
nssm set FlyPrintEdge DisplayName "Fly-Print Edge Service"
nssm set FlyPrintEdge Start SERVICE_AUTO_START

:: 启动服务
net start FlyPrintEdge

:: 停止服务
net stop FlyPrintEdge

:: 删除服务
nssm remove FlyPrintEdge confirm
```

### 使用任务计划程序（备选）

如果没有 NSSM，可以使用 Windows 任务计划程序：

1. 打开"任务计划程序"
2. 创建基本任务
3. 触发器：系统启动时
4. 操作：启动程序 `C:\FlyPrint\start.bat`

---

## 🗑️ 卸载程序

### 方法 1：使用卸载脚本

以管理员身份运行 `C:\FlyPrint\uninstall.bat`

### 方法 2：手动卸载

1. 停止服务：
   ```cmd
   net stop FlyPrintEdge
   ```

2. 删除服务：
   ```cmd
   nssm remove FlyPrintEdge confirm
   ```

3. 删除程序文件：
   ```cmd
   rd /s /q C:\FlyPrint
   ```

---

## 📝 配置说明

### config.json 重要配置项

```json
{
  "api_url": "http://your-cloud-server:8180",
  "auth_url": "http://your-auth-server/api/v1/auth/token",
  "settings": {
    "pdf_printer_path": "C:\\FlyPrint\\portable\\sumatra\\SumatraPDF.exe",
    "libreoffice_path": ""
  },
  "node": {
    "name": "自助终端-001",
    "location": "图书馆一层"
  }
}
```

---

## ⚠️ 常见问题

### 1. 缺少 Python 依赖
**问题**：运行时提示缺少某些模块

**解决**：
```cmd
cd C:\FlyPrint
python -m pip install -r requirements.txt --upgrade
```

### 2. 端口被占用
**问题**：启动失败，提示 7860 端口被占用

**解决**：
- 检查是否已有 FlyPrint 实例运行
- 修改 `main.py` 中的端口号

### 3. 打印机无法发现
**问题**：管理界面看不到打印机

**解决**：
- 确保打印机驱动已正确安装
- 检查 Windows 打印队列中是否能看到打印机

### 4. 服务无法启动
**问题**：`net start FlyPrintEdge` 失败

**解决**：
- 查看事件查看器中的错误日志
- 手动运行 `C:\FlyPrint\start.bat` 查看错误信息

---

## 🔗 相关链接

- **项目主页**：https://github.com/your-org/fly-print-edge
- **云端控制台**：http://your-cloud-server:8180
- **技术支持**：support@your-company.com

---

## 📄 许可证

[您的许可证信息]
