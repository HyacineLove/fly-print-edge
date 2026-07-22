# 发版计划 P0/P1

> **全局计划：** 工作区根目录 `FlyPrint开发计划.md` + `FlyPrint任务清单.md`；全量归档 `FlyPrint总开发计划.md`  
> 目标：2026-07-22 下午 · plan→execute 权威待办 · 与 `fly-print-cloud/docs/agent/release-plan.md` 同步  
> 交付：Compose（含 Demo）+ Edge 安装包 + 第三方简要 Guide

| 产出 | 通过标准 |
|------|----------|
| Compose | `docker compose up --build -d` 后 `:8012` 管理端 + `/integration-demo/` |
| Edge exe | 激活、连 Cloud、默认 IPP、官方扫码可打 |
| Guide | `fly-print-cloud/docs/第三方接入简要指南.md` 能配 Demo 跑通一轮 |
| Demo 流 | 扫码→SSO→提交→终端确认→打印→Demo `completed` |

工作方式：选未完成 P0（无则 P1）→ 对话复述完成定义 → 实现+测试 → 勾选 → 新风险写入「明确不做」或升为 P0/P1。  
状态：`[ ]` 未做 · `[~]` 进行中 · `[x]` 完成（`[x]` 细则见根目录 `FlyPrint任务清单.md`「用法」第 4 条：单测通过 ≠ 已合入 ≠ 已打包/已预演）

## P0

### P0-1 Edge：重启 unconfirmed 补终端上下文

- [x] `_recover_inbox_jobs` 对 `processing` 中断上报带回 `terminal_session_id` / `terminal_ticket_hash` / `integration_request_id`
- [x] 单测：集成中断恢复后 Cloud 不因 `terminal_context_mismatch` 拒绝
- [x] 合入后打安装包（建议 bump 版本）→ `dist/flyprint-edge-setup-1.0.38.exe`（产物不入库）

**完成：** 第三方打印中 Edge 重启后终态可被 Cloud 接受；Demo 不永久卡 dispatched/printing。  
**文件：** `cloud_websocket_client.py`、`job_delivery_store.py`、相关 tests。

### P0-2 演示环境就绪清单（写入 Guide）

- [x] `.env` 密钥替换说明
- [x] Compose 健康检查 `/health`、`/api/v1/health`
- [x] 管理端确认 `livacloud-demo`（entry/callback/CIDR/file host/`allow_private_file_hosts`）
- [x] HMAC 密钥粘贴 `/integration-demo/setup`
- [x] Edge `cloud.base_url` = 手机可达局域网 IP（禁 localhost）
- [x] Edge 激活 + 默认 IPP

**完成：** 干净环境按清单可到 Demo 提交页（清单见 Guide；现场实跑属 P0-4）。

### P0-3 第三方接入简要 Guide

- [x] 边界：第三方不直连打印机；须终端确认
- [x] 入口：扫码→`/entry`→ticket→provider `entry_url`
- [x] `POST /api/v1/integrations/{code}/print-requests` + HMAC
- [x] 文件主机白名单与私网精确主机
- [x] 状态机与 callback
- [x] Demo 逐步操作（密钥、局域网扫码）
- [x] 票据约 5min 等时效；README/AGENTS 链到 Guide

**完成：** Guide 已发布；陌生人可凭 Guide+Compose+exe 完成第三方演示（exe/实跑属 P0-4）。

### P0-4 产物与预演

- [ ] Compose up，Demo 健康
- [x] P0-1 后出 Edge 安装包（`1.0.38`，本地 `dist/`）
- [ ] 官方扫码打印 1 次
- [ ] Demo 全流程到完成 1 次
- [ ] 交付：Compose 说明 + exe + Guide + 本文件勾选结果

## P1（有时间再做）

- [x] P1-1 票据时效提示（ticket ~5min vs Demo 文件 URL ~10min）
- [x] P1-2 Demo setup 未配置/成功态更醒目
- [x] P1-3 管理端「设置」隐藏或标明未开放（无占位入口；下拉已清理）
- [x] P1-4 交付说明写清端口 8012、Demo 路径、默认管理员来源（`docs/演示交付说明.md`）

## 明确不做（本发版日 / M0）

以下 **M0 当天不做**；长期归属见根目录 `FlyPrint开发计划.md`：CI→M3；MinIO 钉版本→M3；`content_hash` 重算→M5；Users/Settings→M2；UNCONFIRMED 静默重打→禁止（策略产品化→M5）；生产 HTTPS/Keycloak→M2。

CI；版本化 DB 迁移（文档或已过时，以 Cloud migrations 为准）；钉死 MinIO 非 latest；`content_hash` 端到端复算；Users/Settings 完整页；UNCONFIRMED 自动解锁（运维 `clear-unconfirmed`）；生产 HTTPS/Keycloak（演示用 builtin）。
