# Edge Admin Config Center Design

**Date:** 2026-05-21

## Goal

将 `fly-print-edge` 现有依赖 `config.json` 的大多数人工配置，迁移到统一的管理页面中完成；在不破坏当前打印机管理能力的前提下，新增一个可交互的“配置中心”，支持：

- 通过 UI 管理云端连接、打印默认设置、运行设置、打印机发现设置
- 对部分配置执行保存后即时生效
- 对必须重启的配置明确提示“需重启 Edge 才生效”
- 保留原有 `node_id`，避免因保存云端配置而重复注册节点
- 敏感字段默认掩码显示，不回显完整明文

## Non-Goals

- 不在这一期移除 `config.json` 作为底层持久化载体
- 不在这一期改造用户侧打印流程
- 不在这一期改造云端协议或引入新的云端字段
- 不在这一期实现多用户权限系统

## Current State

### Existing Configuration Storage

当前配置主要保存在 `config.json`，结构包含：

- `cloud`
- `settings`
- `network`
- `printers`
- `managed_printers`
- `default_printer_id`

`printer_config.py` 负责加载和保存该文件，但目前只提供少量围绕打印机列表的读写方法，没有形成通用的配置访问层。

### Existing Admin UI

当前管理页入口为 `/admin`，前端位于：

- `static/admin/html/index.html`
- `static/admin/main.js`
- `static/admin/css/admin.css`

现有页面重点只覆盖：

- 已管理打印机列表
- 可添加打印机列表
- 默认打印机切换
- 删除打印机
- 云端状态展示

它还不是完整的配置中心。

### Existing Runtime Consumption

当前配置在多个位置被直接读取：

- `main.py` 读取 `settings`、`network`、`cloud`
- `CloudService` 在启动时读取 `cloud`
- `printer_windows.py` 自行再次读取 `config.json` 中的 `settings`

这意味着配置既有“启动期读取”的场景，也有“运行中即时读取”的场景，但边界不统一。

## Product Direction

采用**方案 B：统一成单页工作台**。

保留现有 `/admin` 路由，不再新增第二套配置入口。新的管理页以统一工作台为主，将旧打印机管理能力吸纳到同一信息架构下，避免“旧页面 + 新配置页”并存导致的重复入口和交互冲突。

## UX Structure

### Route Strategy

- 保留 `/admin`
- `/admin` 直接渲染新的统一管理页
- 现有打印机管理区域并入新的页面导航结构

### Page Layout

统一工作台采用左侧导航 + 右侧内容区：

左侧导航分组：

1. 概览
2. 云端配置
3. 打印默认设置
4. 运行设置
5. 打印机发现
6. 打印机管理

顶部全局区域展示：

- 保存状态
- 云端连接状态
- 是否存在“需重启生效”的未应用变更
- 全局操作按钮，例如“保存配置”“测试云端连接”“重新注册节点”

右侧内容区展示当前分组的表单、提示信息、错误信息和操作反馈。

### UX Rules

- 所有中文静态资源统一 UTF-8 编码
- 所有配置字段都必须有标签、说明文案、校验提示
- 每个分组明确标注字段的生效方式：
  - `保存后立即生效`
  - `保存后将尝试重连`
  - `保存成功，需重启 Edge 才生效`
- 保存中必须锁定保存按钮，防止并发写配置
- 保存完成后必须返回结构化反馈，而不是只弹统一“成功/失败”

## Config Scope

### Group 1: Cloud Configuration

纳入 UI：

- `cloud.enabled`
- `cloud.base_url`
- `cloud.auth_url`
- `cloud.client_id`
- `cloud.client_secret`
- `cloud.node_name`
- `cloud.location`
- `cloud.heartbeat_interval`
- `cloud.auto_register`

### Group 2: Print Default Settings

纳入 UI：

- `settings.default_paper_size`
- `settings.default_scale_mode`
- `settings.default_max_upscale`
- `settings.libreoffice_path`
- `settings.pdf_printer_path`

### Group 3: Runtime Settings

纳入 UI：

- `network.bind_address`
- `network.port`

### Group 4: Printer Discovery Settings

纳入 UI：

- `printers.discovery_mode`
- `printers.static_list`

### Out of Scope for Editing in This Phase

以下字段不作为“配置中心主表单字段”处理：

- `managed_printers`
- `default_printer_id`
- `cloud.node_id`

原因：

- `managed_printers` 和 `default_printer_id` 已属于打印机管理行为，应继续通过打印机管理区维护
- `cloud.node_id` 是运行时身份缓存，不应作为普通可编辑文本字段暴露

## Runtime Semantics

### Immediate Apply

以下配置保存后应立即应用：

- 全部 `cloud.*` 可编辑字段
- 全部 `settings.*` 可编辑字段

其中云端配置不是“直接替换内存值后不处理”，而是执行受控的重建流程。

### Restart Required

以下配置保存后只写入 `config.json`，并提示“需重启 Edge 才生效”：

- `network.bind_address`
- `network.port`
- `printers.discovery_mode`
- `printers.static_list`

原因：

- `network.*` 影响 FastAPI / uvicorn 监听方式，当前进程内安全热切换成本高
- `printers.*` 会影响发现策略，当前代码结构下更适合作为启动期配置

### Node Identity Rule

当用户保存云端配置，例如修改：

- `base_url`
- `auth_url`
- `client_id`
- `client_secret`
- `node_name`
- `location`

系统默认行为必须是：

- 保留原 `node_id`
- 停止当前云端连接
- 使用新配置重建认证客户端、API 客户端、WebSocket 客户端、心跳服务
- 若本地配置中已存在 `node_id`，则继续沿用该值
- 不触发重复注册节点

只有当用户显式点击“重新注册节点”时，才允许：

- 清空 `cloud.node_id`
- 重建 `CloudService`
- 重新执行节点注册流程

## Sensitive Field Strategy

### client_secret

`client_secret` 采用“可更新但不回显明文”策略：

- 管理页只显示“已设置”或“未设置”
- 输入框默认空白
- `GET /api/admin/config` 不返回完整 secret
- 若用户保存时该字段为空字符串，表示“保持原值不变”
- 若用户保存时填写非空字符串，表示“用新值覆盖”
- `POST /api/admin/config` 的返回体中也不回传完整 secret

## Backend Architecture

### New Config Service

新增一个专门的配置服务层，例如 `config_service.py`，职责为：

- 从 `PrinterConfig` 读取当前原始配置
- 向前端返回经过筛选和脱敏的配置视图
- 校验用户提交的配置
- 合并更新到原始配置
- 串行写入 `config.json`
- 调用运行时应用逻辑
- 产出结构化的应用结果

`PrinterConfig` 继续负责底层文件读写和现有打印机配置能力，不直接承载管理页交互语义。

### Cloud Runtime Reconfigure

`CloudService` 需要新增明确的运行时重配置能力，例如：

- `reconfigure(new_config: Dict[str, Any], preserve_node_id: bool = True)`

该能力需要完成：

1. 停止当前 WebSocket、心跳、状态上报
2. 替换内部 `config`
3. 重新初始化认证/API/WebSocket相关组件
4. 若 `preserve_node_id=True` 且旧配置已有 `node_id`，则保留它
5. 重新启动连接逻辑
6. 返回成功/失败及失败原因

如果重连失败：

- `config.json` 中的新配置仍然保留
- API 返回“保存成功，但应用失败”的结果
- 页面展示失败原因，并提示用户检查参数或稍后重试

### Settings Runtime Access

当前 `printer_windows.py` 会自行读取 `config.json`。这一期允许保留这种实现，但需要统一原则：

- `settings.*` 的热更新以“更新 `config.json` 后，后续读取生效”为准
- 对于每次打印都会重新读取的设置，保存后即可自然生效
- 若某些设置在内存中有缓存，应在本期一并去掉该缓存或增加刷新入口

## API Design

### GET /api/admin/config

用途：

- 获取配置中心页面需要的全部可编辑配置
- 返回每个分组的字段值和元信息

响应结构应包含：

- `cloud`
- `settings`
- `network`
- `printers`
- `meta`

`meta` 至少包含：

- `restart_required_fields`
- `masked_fields`
- `cloud_secret_configured`

示意：

```json
{
  "success": true,
  "cloud": {
    "enabled": true,
    "base_url": "http://localhost:8012",
    "auth_url": "http://localhost:8012/auth/token",
    "client_id": "edge-default",
    "client_secret": "",
    "client_secret_configured": true,
    "node_name": "my-edge-node",
    "location": "",
    "heartbeat_interval": 30,
    "auto_register": true
  },
  "settings": {
    "default_paper_size": "A4",
    "default_scale_mode": "fit",
    "default_max_upscale": 3.0,
    "libreoffice_path": "",
    "pdf_printer_path": ""
  },
  "network": {
    "bind_address": "127.0.0.1",
    "port": 7860
  },
  "printers": {
    "discovery_mode": "auto",
    "static_list": []
  },
  "meta": {
    "restart_required_fields": [
      "network.bind_address",
      "network.port",
      "printers.discovery_mode",
      "printers.static_list"
    ],
    "masked_fields": ["cloud.client_secret"]
  }
}
```

### POST /api/admin/config

用途：

- 保存配置
- 按字段类别应用运行时变更
- 返回结构化应用结果

请求体：

- 仅包含允许更新的字段
- `client_secret` 为空字符串表示“不修改”

响应结构至少包含：

- `saved`
- `applied_now`
- `restart_required`
- `cloud_reconnected`
- `warnings`
- `errors`

示意：

```json
{
  "success": true,
  "saved": true,
  "applied_now": [
    "cloud.base_url",
    "cloud.auth_url",
    "settings.default_paper_size"
  ],
  "restart_required": [
    "network.port"
  ],
  "cloud_reconnected": true,
  "warnings": [],
  "errors": []
}
```

### POST /api/admin/config/test-cloud

用途：

- 使用表单中的临时参数测试云端连通性
- 不直接保存到 `config.json`

行为：

- 测试 `auth_url` 是否能获取 token
- 测试 `base_url` 的健康检查或认证后请求是否可达
- 返回明确失败原因

### POST /api/admin/node/reregister

沿用现有接口语义，但页面中的文案需要明确：

- 这是一个高风险动作
- 它会清空当前 `node_id`
- 它可能生成新的节点身份

## Validation Rules

### Cloud

- `base_url` 必须是合法 URL
- `auth_url` 必须是合法 URL
- `client_id` 不能为空
- `heartbeat_interval` 必须是正整数

### Settings

- `default_scale_mode` 只允许 `fit | actual | fill`
- `default_max_upscale` 必须是正数
- `libreoffice_path` 和 `pdf_printer_path` 可为空；若非空，则提示路径校验结果

### Network

- `bind_address` 不能为空
- `port` 必须是有效端口号

### Printers

- `discovery_mode` 只允许当前系统支持的值
- `static_list` 必须是结构化列表，不能接受未解析的大段文本

## Frontend Behavior

### State Management

管理页需要新增配置中心状态，包括：

- 当前表单值
- 初始值快照
- 是否有未保存变更
- 是否正在保存
- 最近一次应用结果

### Save Flow

1. 拉取配置
2. 用户编辑
3. 点击保存
4. 前端禁用保存按钮和相关危险操作
5. 调用 `POST /api/admin/config`
6. 用结构化结果刷新页面状态
7. 若存在 `restart_required`，页面显示显著提示

### Secret Field Flow

- 若 `client_secret_configured=true`，输入框显示占位文案，例如“已设置，留空则保持不变”
- 用户不输入时，不发送覆盖动作
- 用户输入新值时，提交该新值

## Encoding Requirement

正式开发时，所有新增或重写的管理页资源必须统一采用 UTF-8：

- `static/admin/html/*.html`
- `static/admin/*.js`
- `static/admin/css/*.css`
- 新增文档与配置相关模板

同时检查当前存在的乱码来源，避免继续混用非 UTF-8 文件。

## Testing Strategy

### Backend Tests

新增测试至少覆盖：

- `GET /api/admin/config` 不回传明文 secret
- `POST /api/admin/config` 在 secret 为空时保持原值
- `POST /api/admin/config` 在 secret 非空时正确覆盖
- 云端配置保存后会触发保留 `node_id` 的重连逻辑
- `network.*` 和 `printers.*` 变更只标记为 `restart_required`
- 配置保存失败或重连失败时返回正确结果

### Frontend Tests

若当前仓库不具备完善前端测试框架，至少保证：

- 表单分组渲染正确
- 保存按钮在请求期间禁用
- `client_secret` 不回显旧值
- 应用结果区域能正确显示“立即生效 / 需重启 / 失败”

### Manual Verification

人工验证至少覆盖：

1. 仅修改 `default_paper_size`，保存后无需重启
2. 修改 `base_url/auth_url` 为正确值，保存后云端自动重连
3. 修改 `base_url/auth_url` 为错误值，保存成功但应用失败，原 `node_id` 保留
4. 修改 `network.port`，页面提示需重启
5. `client_secret` 留空保存时不丢失原值
6. 点击“重新注册节点”时才会清空 `node_id`

## Rollout Plan

建议按以下顺序实施：

1. 后端补配置读取/保存 API 和 `ConfigService`
2. 后端补 `CloudService` 重配置能力
3. 管理页重构为统一工作台
4. 接入配置分组表单和保存反馈
5. 补测试和手工验证

## Risks

- 当前配置读取分散，热更新边界不统一，实施时容易漏掉直接读文件的分支
- 若 `CloudService` 重连流程处理不完整，可能出现“配置已保存，但连接状态卡死”
- 若前端继续沿用旧编码文件，中文仍可能乱码
- 若保存流程没有串行化，可能产生并发覆盖配置的问题

## Acceptance Criteria

当以下条件全部满足时，本设计视为完成：

- 用户无需手工编辑 `config.json` 即可完成大多数日常配置
- `/admin` 成为唯一主管理入口
- 云端配置保存后默认保留原 `node_id`
- 非显式重注册情况下不会重复注册节点
- `client_secret` 不回显明文，但支持更新
- 页面能明确区分“立即生效”和“需重启生效”
- 正式页面不再出现中文乱码
