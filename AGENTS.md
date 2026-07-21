# FlyPrint Edge 开发约定

## Cloud terminal-result protocol (2026-07-21)

- Cloud print work is addressed only by `printer_id`; display names are never a fallback printing target.
- `job_delivery_store.py` is the authoritative SQLite delivery state under `runtime/edge_job_delivery.sqlite3`. It owns both the inbound receipt inbox and the terminal-result outbox; in-memory job maps are acceleration caches only.
- Edge writes the IPP terminal result and one stable UUID `event_id` to SQLite in the same transaction. `completed`, `failed`, `canceled`, and `unconfirmed` remain queued until Cloud sends `job_update_ack/accepted`.
- Reconnection and an unacknowledged result use exponential retry capped at 60 seconds with no expiry. `job_update_ack/rejected` stops retries and remains visible in local Cloud status; it must not be represented as a successful print.
- Restart recovery resumes `received` jobs. A job interrupted while printing becomes `unconfirmed` with `edge_restart_result_unknown`; it is reported but never physically reprinted.

## 生产打印架构

唯一生产链路为：

`PDF / DOCX / 图片 -> 标准打印 PDF -> IPP Print-Job -> 设备 Job ID -> IPP 作业终态`

- `printing/domain.py` 定义请求、参数、状态、错误和用户提示。
- `printing/documents.py` 负责 LibreOffice 转换和 PDF/图片统一排版。
- `printing/ipp_protocol.py` 负责 IPP/2.0 编解码、HTTP 传输和作业操作。
- `printing/ipp_device.py` 负责能力、参数校验、设备状态与故障归一化。
- `printing/discovery.py` 负责 `_ipp._tcp.local.` 发现、URI 构造和 UUID 去重。
- `printing/service.py` 负责串行锁、提交、监控、取消和资源清理。

生产代码禁止加入 Windows Spooler、WSD、RAW Socket、WMI、SumatraPDF、系统默认应用或其他打印回退路径。需要改变链路时，先在对话中明确方案并获得确认。

## 已确认的部署与物理安全边界

- 一套 Edge 设备即一体机：一台终端工控 PC 与一台打印机直连，二者共同代表一个现场终端；正常打印、会话和二维码流程仅服务该终端。
- 正常运行时程序以 kiosk 形式锁定在用户页，终端仅提供触屏操作；本地管理页不对普通使用者开放。
- 一体机后部有物理门锁，只有持钥匙的运维人员打开后才能向工控 PC 接入键鼠维护。因此，在当前确认的部署形态下，本地管理 API 未额外启用应用层鉴权不视为缺陷，它依赖受控物理访问边界。
- Edge 默认应保持回环监听。若改为局域网/公网监听、经代理暴露、启用远程维护，或让普通人员能够进入本地管理页，则上述结论失效；必须先在对话中确认，并设计网络隔离及独立管理鉴权，不能静默扩大暴露面。
- 物理边界不替代 Cloud 对终端身份的密码学验证：Cloud 仍必须做到独立终端凭据与 `node_id` 强绑定；二维码/第三方流程仍必须把 `terminal_ticket`、会话、文件和任务关联起来。

## 实施原则

- 只接受完整 `ipp://` URI；不猜测资源路径，不绕过证书，不支持 IPPS。
- 设备 `job-state=completed` 是成功的唯一完成条件。
- 网络或协议状态不明确时返回 `UNCONFIRMED`，不能推断成功。
- 同一 `printer-uuid` 同时只允许一个 FlyPrint 作业。
- 文档转换、预览和打印使用同一排版模型。
- 可先建立小 Demo 验证协议行为；合入生产后不得保留重复协议实现。
- 文件修改使用小而清晰的模块，避免继续扩大 `main.py` 和 Cloud 适配层。

## 验证

- 开发与构建使用 Python 3.12.10 venv。
- 协议与状态机必须有离线单元测试。
- 真实设备行为必须在网线直连 HP Color LaserJet Pro 3288dn 的目标机器验收。
- 不得用当前开发机的发现结果替代目标机器验收。

## Windows 安装包构建

- PyInstaller 构建环境：`D:\HQIT-LAPTOP\FlyPrint\fly-print-edge\.venv-build-3.12.10\Scripts\pyinstaller.exe`。
- Inno Setup 6.7.3（当前用户安装）的编译器：`C:\Users\HQIT-LAPTOP\AppData\Local\Programs\Inno Setup 6\ISCC.exe`。
- 构建顺序：先在仓库根目录执行 `pyinstaller --noconfirm flyprint-edge.spec`，再执行 `ISCC.exe installer.iss`。
- 安装包输出到 `dist\flyprint-edge-setup-<版本>.exe`；版本号由 `installer.iss` 的 `MyAppVersion` 定义。
- 2026-07-21 已用上述 Inno Setup 6.7.3 路径成功编译 Edge 1.0.32 安装包；后续构建直接复用该路径。
