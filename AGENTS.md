# AGENTS.md

本文件是 `fly-print-edge` 项目的协作与技术上下文，供当前目录及上级 `FlyPrint` 统筹 Agents 使用。内容以当前工作树源码为准；不要因为本文件与历史设计文档或其他分支不一致就擅自回退代码。

## 项目定位

FlyPrint Edge 是部署在打印现场 Windows 电脑上的边缘节点和自助打印 Kiosk。它连接 FlyPrint Cloud，提供本地 FastAPI 服务、用户打印 SPA 和管理 SPA，负责二维码上传、文件预览、打印选项提交、本机打印队列跟踪、故障探测和 Cloud 状态回报。

正式交付目标是 Windows。`printer_linux.py` 是保留的 CUPS/Linux 实验性适配，Linux 代码和测试结果不能作为正式支持承诺。

## 核心架构

### 服务与入口

- `main.py`：FastAPI 单体入口；所有主要路由、启动/关闭生命周期、SSE、文件预览和跨模块编排都在这里。
- `service_main.py`：打包后的后台服务入口，调用 `main.run_server()`。
- `launcher.py`：Windows 托盘程序；负责单实例、启动/重启后台服务、健康检查、打开用户/管理页面、日志和安装目录。
- `windows_startup.py`：HKCU 开机启动项读写。
- `windows_subprocess.py`：Windows 隐藏子进程参数，避免打印探测和转换命令弹出控制台。
- `logging_utils.py`：根据 `config.json` 配置日志级别和 debug 开关。
- `portable_temp.py`：使用项目/安装目录下的 `temp/` 保存临时文件，并清理旧文件。

### Cloud 集成

- `cloud_auth.py`：OAuth2 client-credentials 认证、token 缓存和过期刷新。
- `cloud_api_client.py`：节点注册、打印机注册/删除、批量状态上报和 WebSocket URL 生成。
- `cloud_websocket_client.py`：独立线程和 asyncio loop 的持久 WebSocket 客户端，负责重连、消息分发、上传凭证、打印任务下载和状态回报。
- `PrintJobHandler`（位于 `cloud_websocket_client.py`）：处理 `print_job`、文件下载/复用、打印队列跟踪、故障探测、终态去重及 Cloud/SSE 双向通知。
- `cloud_heartbeat_service.py`：定时上报节点心跳、CPU/内存/磁盘和网络质量。
- `cloud_service.py`：协调认证、REST、WebSocket、心跳、节点重注册、Cloud 重配置和打印机同步。
- `edge_node_info.py`：收集节点名称、MAC、网卡、OS、CPU、内存和磁盘信息。

### 本地打印

- `printer_utils.py`：`PrinterManager` 门面，负责发现、托管列表、默认打印机、状态/队列、能力和打印提交。
- `printer_windows.py`：正式 Windows 实现，包含 Win32/WMI/Spooler、能力查询、纸张/方向/缩放、PDF/Word/图片/Raw 打印和 `WindowsPrintJobMonitor`。
- `printer_linux.py`：CUPS 实验实现。
- `printer_config.py`：唯一配置持久化入口，读写 UTF-8（兼容 BOM）`config.json`。
- `printer_parsers.py`：解析驱动能力输出，包含 Hiti、HP 和 Generic CUPS 解析器。
- `printer_fault_probe.py`：通过 IPP `Get-Printer-Attributes` 探测打印机故障。
- `printer_fault_state.py`：故障原因归类和必须等 clean probe 才清除的故障状态。
- `printer_capability_summary.py`：把打印机能力归一化为前端使用的 duplex/color/page-size 摘要。
- `print_layout.py`：纸张尺寸、DPI、fit/actual/fill、最大放大倍数和物理布局计算。

### 文件与会话

- `interactive_session.py`：进程内维护一个活动用户会话，绑定 upload token、file_id、Cloud job_id 和 SSE 事件。通常状态为 `idle -> awaiting_preview -> preview_ready -> print_submitted -> printing -> completed/failed`。
- `file_manager.py`：统一管理预览源、转换 PDF、打印 artifact、content hash 复用、访问 token、缓存引用和 TTL 清理线程。
- `main.py` 中的 `preview_cache`、`preview_page_cache`、`preview_page_meta`：内存预览缓存，由 `FileManager` 关联清理。

### 前端

- `static/user/`：用户打印 SPA。流程是二维码登录/上传、预览、份数/单双面/彩色选择、提交打印、进度和完成/失败。
- `static/user/modules/app/`：新用户 SPA 控制器、路由、状态和 SSE；`views/` 是视图，`pages/` 是页面交互，`shared/` 提供 API、sessionStorage 会话、能力限制、错误提示和触摸保护。
- `static/admin/`：管理 SPA；`config-actions.js` 管理配置、Cloud 和开机启动，`printer-actions.js` 管理打印机，`render-sections.js` 负责渲染。
- 前端为原生 ES Modules，无 Node 构建链；静态资源由 FastAPI `/static` 挂载。

## HTTP 接口

默认监听 `127.0.0.1:7860`。

用户接口：

- `GET /`：用户入口；`GET /admin`：管理入口。
- `GET /api/status`：在线状态、node_id、托管打印机数量。
- `GET /api/printer/availability`：默认打印机可用/故障状态。
- `GET /api/qr_code`：向 Cloud 请求上传凭证并创建互动会话。
- `GET /api/events`：SSE 长连接，广播 `preview_file`、`error`/`cloud_error`、`job_status` 等事件。
- `GET /api/session/current`：刷新后的当前会话快照。
- `POST /api/preview`：下载/复用文件，生成 PDF/Office/图片预览。
- `POST /api/print`：校验会话、打印机和能力，归一化选项后向 Cloud 提交打印参数。
- `POST /api/cleanup`：清理会话、预览引用和可释放文件。

管理接口（前缀 `/api/admin`）：

- `GET/POST /config`：读取脱敏配置、保存配置；空 `client_secret` 表示保留旧值。
- `POST /cloud/check-register`、`POST /config/test-cloud`：测试 Cloud 并注册/重注册节点。
- `GET /cloud/status`、`POST /node/reregister`：Cloud 状态和节点重注册。
- `GET/POST /system/startup`：开机启动状态。
- `GET /printers/managed`、`GET /printers/discovered`：托管/发现打印机。
- `POST /printers/add`、`POST /printers/default`：添加打印机和设置默认打印机。
- `DELETE /printers/{printer_id}`、`POST /printers/{printer_id}/reregister`：删除和重注册打印机。

管理 API 当前没有启用 `X-API-Key` 认证，因此服务必须保持 loopback 绑定。任何绑定 `0.0.0.0` 的需求都必须先设计认证、访问控制和防火墙策略。

## 关键运行时流程

### 启动

FastAPI startup 读取配置并配置日志，创建 `PrinterManager`、`ConfigService`、`FileManager` 和 `CloudService`；文件管理器默认每 300 秒清理、文件 TTL 为 1800 秒。Cloud 服务注册 `preview_file`、`error`、`cloud_error`、`job_status` 监听器，然后启动 WebSocket、心跳和打印机状态报告。Cloud 不可用时 Edge 可以启动，但二维码流程会提示离线。

### 用户打印

1. `/api/qr_code` 检查节点、托管/默认打印机和故障状态，向 Cloud 请求短期上传凭证。
2. 用户上传后，Cloud 通过 WebSocket 推送 `preview_file`。
3. 互动会话只接受当前会话绑定的预览事件；合法 `content_hash` 为 64 位十六进制字符串，可命中本地缓存复用源文件。
4. PDF 使用 PyMuPDF，Office 文件通过 WPS COM、LibreOffice 或 Word COM 转换，图片使用 Pillow；预览结果按 file/page/options 缓存。
5. `/api/print` 校验会话和能力，依据 `settings.copies_min/max` 限制份数，向 Cloud 发送 `submit_print_params`。
6. `PrintJobHandler` 下载或复用文件，调用 `PrinterManager.submit_print_job_with_cleanup`，由 Windows 打印实现提交并跟踪 Spooler 任务。
7. 状态通过 WebSocket 回报 Cloud，并经主事件循环转为 SSE；完成、错误、取消和打印机故障驱动用户端状态。
8. 清理预览引用时，content-hash 共享源文件只有最后一个引用释放后才删除。

WebSocket 在 daemon 线程自己的 asyncio loop 中运行。回调不能直接操作 FastAPI loop 或 SSE 队列，必须通过 `main_loop.call_soon_threadsafe()` 回到主 loop。新增 Cloud 消息类型时，要同步考虑监听器、会话过滤、Cloud 回报、SSE 前端处理和重连/重复消息。

## 配置与安全

`config.example.json` 是模板，实际运行配置是被 `.gitignore` 忽略的 `config.json`。主要分组为：`cloud`、`network`、`settings`、`printers`、`managed_printers` 和 `default_printer_id`。

没有数据库；`config.json` 是持久化真源，`PrinterConfig` 是唯一磁盘 I/O 入口。`config.json` 含 Cloud client secret，不得提交 Git、打入公开包、截图或日志。不要提交用户上传文件、日志、临时文件、虚拟环境和构建产物。

管理接口无内置认证；默认只能绑定 loopback。预览/下载路径必须继续校验 file_id、content_hash、文件名、Cloud URL 和缓存路径，防止任意文件读取。

## 开发、测试与发布

不要复用仓库中可能失效的 `venv`；建议创建新环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest pyinstaller
```

常用命令：

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m unittest discover tests
.\.venv\Scripts\python.exe release\build_installer.py --version 1.0.0
```

打包链路是 `release/build_installer.py` -> `flyprint-edge.spec` -> `dist/flyprint-edge/` -> Inno Setup `installer.iss`，生成 `flyprint-edge.exe` 后台服务、`flyprint-launcher.exe` 托盘程序和安装程序。真实 Windows 打印机、Office 转换环境和 Inno Setup 是发布验收边界。

`tests/` 主要是 unittest、API 契约和静态结构测试；`edge_upload_preview_e2e.py`、`edge_preview_perf.py`、`error_detection_probe.py` 依赖运行中的 Cloud/Edge 或真实硬件，不能视为普通离线单元测试。`tools/diagnostics/` 中的脚本可能直接影响真实打印队列，运行前必须确认目标设备。

## 修改规范与已知限制

- 先读相关测试再改行为；修改 API 时同步更新前端、错误码和契约测试。
- 不要继续无条件扩大 `main.py`、`cloud_websocket_client.py`、`printer_windows.py`；纯逻辑优先放入小模块并添加离线测试。
- 不要阻塞 FastAPI event loop；打印、下载、Office 转换、WMI/IPP 探测和 Cloud 调用要遵守现有线程/异步边界。
- 不要破坏 `FileManager` 的引用计数/所有权语义，也不要让不属于当前会话的 Cloud 事件进入用户 SSE。
- Windows 打印修改必须考虑真实驱动、Spooler、权限、PDF/Office/图片、单双面、彩色、缺纸、卡纸、离线、取消、重连和重复文件。
- Cloud 与 Edge 尚未建立正式协议版本和自动兼容矩阵；跨端消息字段修改需要协调 Cloud。
- `requirements.txt` 只有最低版本，没有 lock/constraints；正式 CI 应固定 Python 和依赖版本。

若需要额外设计或验收说明，请在本文件中加入“详见 XXX”并指向对应文档，避免把主文件变成过度冗长的历史记录。
