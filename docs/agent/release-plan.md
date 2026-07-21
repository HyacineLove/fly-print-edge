# FlyPrint 发版开发计划（P0 / P1）

> 目标发版窗口：2026-07-22 下午  
> 用途：plan → execute 循环的权威待办清单。上下文丢失时先读本文件，再动手改代码。  
> 配套交付物：Cloud Docker Compose（含 Demo）、Edge 安装包、第三方接入简要 Guide。  
> 同步副本：`fly-print-cloud/docs/agent/release-plan.md`（两仓内容应保持一致）。

## 交付物验收标准

| 产出 | 来源 | 通过标准 |
|------|------|----------|
| Docker Compose 包 | `fly-print-cloud` | `docker compose up --build -d` 后 `:8012` 可进管理端与 `/integration-demo/` |
| Edge 安装包 | `fly-print-edge` → `flyprint-edge-setup-*.exe` | 激活、连 Cloud、默认 IPP、官方扫码可打 |
| 第三方接入简要 Guide | 建议 `fly-print-cloud/docs/第三方接入简要指南.md` | 按文档能配好 Demo 并走完一轮 |
| Demo 完整业务流 | Compose 内 `livacloud-demo` + Edge | 扫码 → SSO → 提交 → 终端确认 → 打印 → Demo 显示 completed |

## 工作方式（plan-execute）

1. 选一条未完成的 P0（没有 P0 再选 P1）。
2. 在对话中复述该条的「完成定义」。
3. 实现 → 跑相关测试 → 勾选本文件中的 checkbox。
4. 若发现新风险：写入「已知限制 / 发版后」或提升为新的 P0/P1，不要只留在聊天里。
5. 发版前：官方流 + Demo 流各预演一次，并勾选「发布预演」。

状态约定：`[ ]` 未做 · `[~]` 进行中 · `[x]` 完成

---

## P0 — 发版前必须完成

### P0-1 Edge：重启 `unconfirmed` 补终端上下文

- [ ] 实现：`_recover_inbox_jobs` 对 `processing` 中断任务上报时，从 inbox payload 带回 `terminal_session_id` / `terminal_ticket_hash` / `integration_request_id`
- [ ] 单测覆盖：集成任务中断恢复后 Cloud 不会因 `terminal_context_mismatch` 拒绝
- [ ] 合入后再打安装包（建议版本 bump，如 1.0.37）

**完成定义：** 第三方任务在打印中 Edge 重启后，终态可被 Cloud 接受；Demo 订单不会永久卡在 dispatched/printing。

**主要文件：** `cloud_websocket_client.py`、`job_delivery_store.py`、相关 tests。

### P0-2 演示环境就绪清单（写入 Guide 或 Release Checklist）

- [ ] `.env` 密钥替换说明（Postgres / Admin / JWT / FileAccess / MinIO / Demo 管理密码）
- [ ] Compose 健康检查步骤（`/health`、`/api/v1/health`）
- [ ] 管理端创建/确认 `livacloud-demo`（entry、callback、CIDR、file host、`allow_private_file_hosts`）
- [ ] 一次性 HMAC 密钥粘贴到 `/integration-demo/setup`
- [ ] Edge：`cloud.base_url` 使用手机可达局域网 IP（禁止演示用 localhost）
- [ ] Edge：激活、绑定默认 IPP 打印机

**完成定义：** 按清单可在干净环境从零走到 Demo 提交页，无需口头补充步骤。

### P0-3 第三方接入简要 Guide（新建文档）

- [ ] 角色与边界（第三方不直连打印机；必须终端确认）
- [ ] 入口：扫码 → `/entry` → `terminal_ticket` → provider `entry_url`
- [ ] `POST /api/v1/integrations/{code}/print-requests` + HMAC 头说明
- [ ] 文件主机白名单与私网精确主机策略
- [ ] 状态机与 callback（`/api/print/callback`）
- [ ] **用 Demo 跑通的逐步操作**（含密钥、局域网扫码）
- [ ] 票据约 5 分钟等时效说明
- [ ] README 或 AGENTS 链到该 Guide

**建议路径：** `fly-print-cloud/docs/第三方接入简要指南.md`

**完成定义：** 不熟悉项目的人只凭 Guide + Compose + Edge 安装包能完成一次第三方演示流。

### P0-4 打齐产物并发布预演

- [ ] Cloud：`docker compose up --build -d`，Demo 健康
- [ ] Edge：P0-1 合入后 PyInstaller + Inno Setup 出安装包
- [ ] 联调：官方扫码打印 1 次成功
- [ ] 联调：Demo 全流程到「打印完成」1 次成功
- [ ] 交付打包：Compose 目录说明 + exe + Guide + 本计划勾选结果

**完成定义：** 预演记录可复述；发版演示不依赖现场现改代码。

---

## P1 — 强烈建议（有时间则做）

### P1-1 票据时效体验

- [ ] Guide / 入口页提示终端票据约 5 分钟
- [ ] 尽量统一或文档化：票据 TTL vs Demo 文件 URL TTL（约 10 分钟）差异

### P1-2 Demo setup 可发现性

- [ ] 未配置 HMAC 时醒目提示
- [ ] 配置成功后有明确成功态（避免演示现场误以为已就绪）

### P1-3 管理端占位收敛

- [ ] 头像下拉「设置」：隐藏或标明未开放（避免验收当成缺功能）

### P1-4 Compose 发版自说明

- [ ] 固定演示端口 `8012`、Demo 路径、默认管理员来源写进交付说明或 Guide 附录

---

## 明确不做（发版后 / 已知限制）

- CI 流水线
- 版本化 DB 迁移与回滚工具
- MinIO 镜像钉死非 `latest`
- `content_hash` 端到端字节复算
- Users / Settings 完整页面
- UNCONFIRMED 自动解锁（保持运维 `clear-unconfirmed`；Guide 写操作路径）
- 生产 HTTPS / Keycloak 切换（演示用 builtin）

---

## 建议时间盒

```text
发版前一天
  ├─ P0-1 代码 + 单测
  ├─ P0-3 Guide 初稿
  └─ P0-4 Cloud compose 预构建

发版当天上午
  ├─ P0-4 Edge 安装包
  ├─ P0-4 官方 + Demo 预演
  ├─ P0-2 / P0-3 按预演改准
  └─ 可选：P1 能做几条做几条

发版当天下午
  └─ 交付与现场演示
```

## 关联文档

- Cloud：`docs/agent/architecture-and-protocols.md`、`operations-and-verification.md`、`change-rules.md`
- Edge：`docs/agent/architecture-and-protocols.md`、`development-and-verification.md`
- 仓库入口：各仓 `AGENTS.md`
