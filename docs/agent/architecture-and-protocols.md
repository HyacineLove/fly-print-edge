# FlyPrint Edge 架构与协议说明

## Cloud terminal-result protocol (2026-07-21)

- Cloud print work is addressed only by `printer_id`; display names are never a fallback printing target.
- `job_delivery_store.py` is the authoritative SQLite delivery state under `runtime/edge_job_delivery.sqlite3`. It owns both the inbound receipt inbox and the terminal-result outbox; in-memory job maps are acceleration caches only.
- Edge writes the IPP terminal result and one stable UUID `event_id` to SQLite in the same transaction. `completed`, `failed`, `canceled`, and `unconfirmed` remain queued until Cloud sends `job_update_ack/accepted`.
- Reconnection and an unacknowledged result use exponential retry capped at 60 seconds with no expiry. `job_update_ack/rejected` stops retries and remains visible in local Cloud status; it must not be represented as a successful print.
- Restart recovery resumes `received` jobs. A job interrupted while printing becomes `unconfirmed` with `edge_restart_result_unknown`; it is reported but never physically reprinted.

## Interactive preview binding repair (2026-07-21)

- A third-party `preview_file` is accepted only for the current `terminal_session_id`. If the local session has no ticket hash yet, the first valid Cloud preview binds `terminal_ticket_hash` and `integration_request_id`; subsequent events require an exact match.
- After binding an integration preview, Edge reports one `terminal_session_state` to Cloud. The user must still confirm print parameters before Cloud creates the standard job.
- The Cloud-job binding callback must not depend on an undefined delivery result variable. It binds the already-confirmed session/job once and reports the session state once.

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

## 二维码入口 URL 语义

- 用户页二维码只有 `/api/qr_code` 一条生成路径。Cloud 返回相对 `/entry?token=...`，Edge 沿用既有逻辑，以 `cloud.base_url` 拼接并将 `localhost`/`127.0.0.1` 改写为 Edge 本机局域网 IP。
- 手机先进入 Cloud Entry 选择官方或第三方；官方再进入既有 `/upload`，第三方仅接收 Cloud 签发的独立终端票据。不得恢复 `/api/integration/terminal-ticket` 等第二套二维码接口。
- 因为二维码公开地址由 Edge 的 `cloud.base_url` 生成，Cloud Compose 默认 `EXTERNAL_API_URL=http://localhost:8012` 不影响该局域网扫码链路。

## 第三方交互式预览协议（2026-07-21）

- `preview_file` 的第三方上下文为可选字段：`terminal_session_id`、`terminal_ticket_hash`、`integration_request_id` 和建议的 `print_options`。只有三项上下文与当前活动会话完全一致时才绑定；官方预览不要求这些字段。
- 第三方参数只负责初始化用户页。用户确认后 `/api/print` 通过 `submit_print_params` 回传完整上下文，Cloud 才能创建唯一标准任务；Edge 后续仍只接受 FlyPrint 内部文件 URL 和 Cloud `printer_id`。
- 重复的同一集成预览按请求 ID 幂等接收；跨会话、票据错配或集成请求错配必须拒绝。不得为第三方增加直接打印或绕过用户确认的路径。
- `tests/ipp_completed_simulator.py` 仅用于自动测试，支持能力查询、Print-Job 和 completed 终态；它不打入生产运行路径，也不能作为真实打印机兜底。
- 2026-07-21 全量执行 192 项 Edge 测试通过，其中包含第三方预览绑定、上下文回传、官方流程回归和测试 IPP completed。
