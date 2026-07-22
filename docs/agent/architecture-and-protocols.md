# Edge 架构与协议

## 生产打印链路（唯一）

`PDF/DOCX/图片 → 标准 PDF → IPP Print-Job → 设备 Job ID → IPP 终态`

| 模块 | 职责 |
|------|------|
| `printing/domain.py` | 请求、参数、状态、错误、用户提示 |
| `printing/documents.py` | LibreOffice 转换、PDF/图片排版 |
| `printing/ipp_protocol.py` | IPP/2.0 编解码与传输 |
| `printing/ipp_device.py` | 能力、参数校验、故障归一化 |
| `printing/discovery.py` | `_ipp._tcp.local.` 发现、URI、UUID 去重 |
| `printing/service.py` | 串行锁、提交、监控、取消、清理 |

禁止：Windows Spooler / WSD / RAW / WMI / SumatraPDF / 系统默认应用等回退。改链路须先确认。

硬约束：完整 `ipp://` URI；成功唯一条件为设备 `job-state=completed`；不明则 `UNCONFIRMED`；同一 `printer-uuid` 同时一作业；预览与打印共用排版模型。

## 终端结果协议

- 任务寻址只用 `printer_id`，显示名不作打印目标。
- 权威状态：`job_delivery_store.py` → `runtime/edge_job_delivery.sqlite3`（inbox + outbox）；内存 map 仅缓存。
- IPP 终态与稳定 UUID `event_id` 同事务写入 SQLite；`completed/failed/canceled/unconfirmed` 在收到 `job_update_ack/accepted` 前保持排队。
- 重连/未 ACK：指数退避上限 60s、不过期。`rejected` 停重试，记本地通信故障，不记为打印成功。
- 重启：恢复 `received`；打印中断 → `unconfirmed` + `edge_restart_result_unknown`，上报但绝不重打。

## 二维码与第三方预览

- 二维码仅 `/api/qr_code`。Cloud 回相对 `/entry?token=...`；Edge 用 `cloud.base_url` 拼接，并把 `localhost`/`127.0.0.1` 改写为本机局域网 IP（**仅适合 http 演示**；HTTPS 请直接配证书域名，禁止 `https://localhost` + 改写）。禁止第二套二维码接口。
- `cloud.base_url` 支持 **http 与 https**；WebSocket 由 `url_scheme.py` 映射为 **ws / wss**（受信证书，无自签）。REST 与下载跟随同一 base_url。
- `preview_file` 第三方可选：`terminal_session_id`、`terminal_ticket_hash`、`integration_request_id`、建议 `print_options`。三项与当前会话一致才绑定；官方预览不要求。
- 会话尚无 ticket hash 时，首次有效预览绑定 hash 与 `integration_request_id`，并上报一次 `terminal_session_state`；用户确认参数后 Cloud 才建标准任务。
- 用户确认后 `/api/print` → `submit_print_params` 回传完整上下文；后续只接受内部文件 URL + Cloud `printer_id`。禁止第三方直打或跳过确认。
- `tests/ipp_completed_simulator.py` 仅测试，不进生产路径。

## 部署与安全边界

- 一体机 = 工控 PC + 直连打印机；kiosk 锁用户页；本地管理依赖物理门锁，默认回环监听。
- 改为非回环/代理暴露/远程维护前须确认并补鉴权。
- 物理边界不替代 Cloud 对终端身份的密码学校验（凭据与 `node_id` 绑定；ticket/会话/文件/任务关联）。
