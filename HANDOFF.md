# FlyPrint Edge 交接文档

面向接手开发的**关键信息清单**，便于快速接手与二次开发。项目仅保留两份文档：**README.md**（快速启动与概览）、**HANDOFF.md**（本文，完整交接信息）。

---

## 1. 关键信息一览

| 类别 | 内容 |
|------|------|
| **定位与范围** | Edge 角色、与 Cloud 的关系、交付边界 |
| **配置入口** | 唯一配置 `config.json`、模板 `config.example.json`、敏感项说明 |
| **架构与启动** | 入口 main.py、启动脚本、端口与绑定 |
| **目录与模块** | 项目结构、核心模块职责 |
| **API 与前端** | 路由清单、静态页面、SSE |
| **云端对接** | base_url/auth_url 约定、WebSocket、注册/心跳/状态/二维码 URL |
| **认证** | OAuth2 Client Credentials、Cloud scope |
| **测试与脚本** | tests/ 下脚本说明与运行方式 |
| **部署与排错** | 环境要求、安装、验证、常见问题、开机自启 |
| **已知待办与注意** | TODO、缩放模式、静态资源大小写、.gitignore 要点 |
| **推荐阅读** | README.md → 本文档 |

---

## 2. 定位与范围

- **FlyPrint Edge**：边缘端打印服务，部署在门店/办公室，管理本机打印机，与 FlyPrint Cloud 协同。
- **核心能力**：本地打印机发现与管理、用户端 Kiosk（扫码上传→预览→打印）、管理端配置界面、通过 WebSocket + REST 与 Cloud 同步（节点注册、打印机注册、心跳、状态上报、接收下发任务与上传凭证）。
- **交付范围**：本仓库为 **Edge 端**（Python + FastAPI + 静态前端）；Cloud 端为独立项目，Edge 通过 `config.json` 中的 `base_url` / `auth_url` 对接。

---

## 3. 配置入口

- **唯一配置**：`config.json`（已加入 .gitignore，不提交）。
- **模板**：复制 `config.example.json` 为 `config.json` 后按需修改。
- **敏感项**：`cloud.client_secret`（需与 Cloud 后台 OAuth2 客户端一致）、运行后可能写入 `cloud.node_id`（节点注册后缓存，勿提交）。
- **主要字段**：
  - `network.bind_address` / `network.port`：服务监听（默认 `127.0.0.1:7860`，局域网访问可改为 `0.0.0.0`）。
  - `cloud.enabled` / `cloud.base_url` / `cloud.auth_url` / `cloud.client_id` / `cloud.client_secret` / `cloud.node_name` / `cloud.location` / `cloud.auto_register` / `cloud.heartbeat_interval`。
  - `managed_printers`：本机管理的打印机列表；`default_printer_id`：默认打印机 ID。
  - `printers.discovery_mode`（`auto` / `static`）、`printers.static_list`。
  - `settings`：可选（如默认纸张、缩放模式等）。示例：`default_paper_size`、`default_scale_mode`（fit/actual/fill）、`default_max_upscale`。

**云端 URL 示例**（子路径须包含在 base_url/auth_url 中）：
- Cloud 根路径（如 `http://host:8012`）：`base_url: "http://host:8012"`，`auth_url: "http://host:8012/auth/token"`。
- Cloud 子路径（如 `https://example.com/fly-print-api`）：`base_url: "https://example.com/fly-print-api"`，`auth_url: "https://example.com/fly-print-api/auth/token"`。

---

## 4. 架构与启动

- **技术栈**：Python 3.10+、FastAPI、uvicorn；前端为静态 HTML/CSS/JS（无构建步骤）。
- **入口**：`main.py`，直接运行即启动服务。
- **启动方式**：
  - **Windows**：`.\start.ps1`（可选 `-Setup` 创建 venv 并装依赖，`-Clean` 清理 venv 后重建）。
  - **Linux/macOS**：`./start.sh`（逻辑类似）。
  - **手动**：`python -m venv venv` → 激活 venv → `pip install -r requirements.txt` → `python main.py`（或 `uvicorn main:app --host 0.0.0.0 --port 7860`）。
- **端口与绑定**：由 `config.json` 的 `network.port`（默认 7860）和 `network.bind_address` 决定；`main.py` 末尾从 config 读并传给 uvicorn。

---

## 5. 目录与模块

```
fly-print-edge/
├── main.py                 # FastAPI 应用、路由、SSE、预览/打印/清理 API
├── config.json             # 运行时配置（不提交）
├── config.example.json     # 配置模板
├── requirements.txt
├── start.ps1 / start.sh
├── README.md / HANDOFF.md
├── cloud_service.py        # 云端服务编排（认证、注册、WS、心跳、状态上报）
├── cloud_auth.py           # OAuth2 Client Credentials 取 token
├── cloud_api_client.py     # REST：注册节点、打印机、状态批量上报、WS URL
├── cloud_websocket_client.py  # WebSocket 连接、心跳、收任务/预览/凭证/错误
├── cloud_heartbeat_service.py # 定时心跳（WS）+ 可选延迟探测
├── printer_config.py       # config.json 读写、打印机列表与默认打印机
├── printer_utils.py        # PrinterManager、发现、队列、提交任务
├── printer_windows.py       # Windows 打印机实现（含 WMI/win32）
├── printer_linux.py        # Linux 打印机实现
├── printer_parsers.py      # 队列/状态解析
├── edge_node_info.py       # 节点注册 payload
├── file_manager.py         # 预览文件生命周期、缓存清理
├── portable_temp.py        # 项目内 temp 目录（可移植）
├── tests/                  # 测试与探测脚本（需在项目根目录运行）
│   ├── test_letter_invoice_fix.py   # Letter 发票打印修复验证
│   ├── test_paper_detection.py      # 纸张尺寸自动检测（PDF/Word）
│   ├── test_printer_system_check.py # 打印机检测与参数（Windows）
│   └── error_detection_probe.py     # 错误检测探测（缺纸/卡纸等）
└── static/
    ├── index.html          # 根路径 → 重定向到 user
    ├── user/               # 用户端 Kiosk（扫码、预览、打印）
    └── admin/              # 管理端（打印机、云端状态、重注册等）
```

---

## 6. API 与前端

- **页面**：`/` → `static/index.html`（重定向到 `/static/user/index.html`）；`/admin` → `static/admin/html/index.html`。
- **用户端 API**（Kiosk）：`GET /api/status`、`GET /api/qr_code`、`GET /api/events`（SSE）、`POST /api/preview`、`POST /api/print`、`POST /api/cleanup`。
- **管理端 API**（`/api/admin` 前缀）：`POST /node/reregister`、`GET /cloud/status`、`GET /printers/managed`、`GET /printers/discovered`、`POST /printers/add`、`POST /printers/default`、`DELETE /printers/{printer_id}`、`POST /printers/{printer_id}/reregister`。
- **SSE**：`/api/events` 推送云端下行消息（如 preview_file、cloud_error、job_status）到前端。

---

## 7. 云端对接

- **URL 约定**：`cloud.base_url` 为 Cloud API 根（**须含子路径**，若 Cloud 子路径部署）。Edge 在此基础拼接：REST（`/api/v1/edge/register`、`/api/v1/edge/{node_id}/printers`、`/api/v1/edge/{node_id}/printers/status` 等）、WebSocket（`/api/v1/edge/ws?node_id=xxx`）、健康检查（`/api/v1/health`）。`auth_url` 为 OAuth2 token 端点完整 URL（同样含子路径）。
- **流程**：启动后若 `cloud.enabled` 且 `auto_register`，先 REST 注册节点并缓存 `node_id` → 建立 WebSocket → 心跳与状态上报；接收 print_job、preview_file、upload_token、error 等；用户端二维码为「base_url + 云端返回的 web_url 路径」，已按子路径正确拼接。
- **认证**：Client Credentials，scope 含 `edge:register`、`edge:heartbeat`、`edge:printer` 等（见 Cloud 文档）。

---

## 8. 认证与权限

- Edge 不提供用户登录；与 Cloud 的认证为 **OAuth2 Client Credentials**（client_id + client_secret），Cloud 侧需预先配置对应客户端与 scope。
- 管理端 API 当前无鉴权（API Key 已预留但未启用），若需可再接入。

---

## 9. 测试与脚本

所有测试/探测脚本位于 **tests/**，需在**项目根目录**执行。脚本内通过 `sys.path.insert(0, 项目根)` 导入 `printer_windows`、`printer_utils` 等。

| 文件 | 说明 |
|------|------|
| `test_letter_invoice_fix.py` | Letter 尺寸发票打印修复验证（纸张识别、SumatraPDF 参数） |
| `test_paper_detection.py` | 纸张尺寸自动检测（PDF/Word 识别、`_identify_paper_size`） |
| `test_printer_system_check.py` | 打印机检测与参数传递（系统打印机列表、安装状态，Windows） |
| `error_detection_probe.py` | 错误检测探测（缺纸/卡纸/缺墨等），支持 `--trigger-print`、`--continuous`、`--output` 等 |

运行示例（在项目根目录、激活 venv 后）：
```bash
python tests/test_letter_invoice_fix.py
python tests/test_paper_detection.py
python tests/test_printer_system_check.py
python tests/error_detection_probe.py --help
python tests/error_detection_probe.py --printer-name "打印机名" --trigger-print --pdf-path test.pdf
```

---

## 10. 部署与排错

**环境要求**：Windows 10/11 或 Linux；Python 3.10+；需能访问 Cloud 的局域网或公网。Windows 安装 Python 时勾选 “Add Python to PATH”。PowerShell 若禁止脚本执行，先运行：`Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`。

**安装**：将项目复制到目标机器 → 可选 `python -m venv venv` → 激活 venv → `pip install -r requirements.txt`（国内慢可用 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）。

**验证**：启动后访问 `http://localhost:7860`（用户端）、`http://localhost:7860/admin`（管理端）；若启用云端，在 Cloud 管理后台应能看到新节点。

**常见问题**：
- **SSL: CERTIFICATE_VERIFY_FAILED**：检查 URL 是否误用 `https://`，当前以 HTTP 为主时可改为 `http://`。
- **无法连接云端**：检查 `cloud.base_url`/防火墙/端口；确认 `client_secret` 与 Cloud 一致。
- **打印机检测不到**：Windows 下确认打印机在“设备和打印机”中已安装；网络打印机需与 Edge 同网段。
- **上传后无法打印**：看控制台日志；确认文件格式支持（PDF、Word、图片等）；Word 转换依赖 LibreOffice 或系统 Office。

**开机自启（Windows）**：任务计划程序 → 触发器“计算机启动时” → 操作“启动程序”：程序填 `python.exe` 或 venv 内 python，参数 `main.py`，起始位置为项目根；或将 `start.bat`（cd 到项目根、call venv\Scripts\activate.bat、python main.py）的快捷方式放入“启动”文件夹。

---

## 11. 已知待办与注意

**TODO**：Windows MSI 构建（WiX）；接收云端“节点禁用”消息并在前端显式提示；节点禁用时暂停处理云端下发任务；恢复时自动恢复。

**缩放模式（scale_mode）**：`fit`（等比缩放完整保留）、`actual`（仅超出时缩小）、`fill`（铺满可打印区域，可能裁切）。可在 `settings.default_scale_mode` 等配置；预览与打印逻辑在 main 中与 Cloud 约定一致。

**静态资源**：`static/index.html` 重定向到 `/static/user/index.html`（小写）。若实际文件名为 `Index.html`，在区分大小写的系统（如 Linux）可能 404，建议统一为小写或确认部署环境。

**.gitignore 要点**：已忽略 `config.json`、`venv`/`.venv`、`__pycache__`、`build/`、`dist/`、`temp/`、`*.log`、`.env` 等；`config.example.json` 与 `tests/` 会提交。仅忽略目录 `test/`，使用 `tests/` 不会被忽略。

---

## 12. 推荐阅读顺序

1. **README.md** — 启动步骤、功能、结构、亮点。  
2. **HANDOFF.md**（本文）— 完整交接信息与排错。

**交接完成时**：请确认已阅读上述两份文档，并能在本地通过 `config.example.json` → `config.json` 配置后成功启动、连接 Cloud（若启用）并完成一次扫码→预览→打印流程。
