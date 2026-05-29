# User 端 SPA 与 SSE 生命周期稳定化设计

**Date:** 2026-05-26

## Goal

将 `static/user/` 从“多 HTML 页面 + 页面级初始化 + 页面级 SSE”重构为“单入口原生 JS SPA + 应用级单例 SSE 连接”，确保用户端从打开页面开始，到主动关闭前端页面为止，应用自身不会因为页面切换导致 SSE 断开重连。

本次设计的直接目标是让以下流程在同一个浏览器运行时中完成：

- 二维码页
- 预览页
- 打印中页
- 完成页
- 自动回到二维码页，进入下一轮

对于后端日志和连接观测，目标是：

- 正常业务流转中，不再因为 `window.location.href` 切页导致 `/api/events` 连接数抖动
- 前端生命周期内只建立一次逻辑上的用户端实时连接
- 关闭前端页面后，连接才从 `1` 变为 `0`

## Non-Goals

- 本次不改 `static/admin/`
- 本次不把 `user` 与 `admin` 合并为一个超大 SPA
- 本次不重做用户端整体视觉风格
- 本次不引入 Vite / Webpack / React / Vue 等构建工具或框架
- 本次不把 SSE 改为 WebSocket
- 本次不实现完整事件历史回放系统

## Current State

### Frontend

当前 `user` 端已经完成“原生模块化拆分”，但仍然是“多页面流程”：

- `static/user/Index.html` 负责跳转到 `html/login.html`
- `static/user/html/login.html`
- `static/user/html/preview.html`
- `static/user/html/printing.html`
- `static/user/html/done.html`

当前运行方式是：

- 每个 HTML 都加载 `static/user/main.js`
- `main.js` 根据 `body[data-page]` 调用对应 `init*Page()`
- `login.js`、`preview.js`、`printing.js` 各自创建自己的 `createSseConnection()`
- 页面间通过 `window.location.href` 跳转

这意味着：

- 每次切页都会销毁整个 JS 上下文
- `EventSource` 必然关闭并重新建立
- 应用状态只能依赖 `sessionStorage` 和少量运行时恢复

### SSE

当前 `/api/events` 的前端特点：

- 没有 `Last-Event-ID`
- 没有事件序号
- 没有快照恢复接口
- 前端 `createSseConnection()` 是页面级对象，不是应用级对象

因此当前 SSE 只能做到“某个页面内部的自动重连”，做不到“跨页面流程中的持续连接”。

### Backend

后端已经有以下能力，可作为 SPA 方案基础：

- `InteractiveSessionManager` 已维护当前活跃交互会话
- `preview_file` / `job_status` / `cloud_error` 会被绑定到当前活跃会话
- `/api/qr_code` 会创建会话并返回 `session_id`
- `/api/preview`、`/api/print`、`/api/cleanup` 已具备会话校验逻辑

但还缺少一个“给 SPA 做冷恢复”的明确会话快照接口。

## Product Direction

采用“单入口 SPA + 应用级状态机 + 应用级单例 SSE”的方案。

核心原则：

1. 浏览器只加载一个用户端 HTML 壳
2. 二维码 / 预览 / 打印中 / 完成都作为同一页面内的四个视图
3. SSE 连接只在应用启动时创建一次，由应用级对象持有
4. 页面流转只切换视图，不做整页跳转
5. 后端补一个当前交互会话快照接口，用于真正断线或刷新后的恢复

## Frontend Architecture

### Entry Shell

用户端改为单入口：

- `static/user/index.html`

该文件只承担：

- 全局壳
- `#app` 视图挂载点
- 顶部 toast
- 全局时间显示
- 必要的全局遮罩占位
- 加载 `app.js`

它不承载完整四个页面的静态大块 HTML，不会变成难读的大文件。

### App Structure

建议目录：

- `static/user/index.html`
- `static/user/app.js`
- `static/user/modules/app/router.js`
- `static/user/modules/app/app-state.js`
- `static/user/modules/app/app-controller.js`
- `static/user/modules/app/sse-client.js`
- `static/user/modules/views/login-view.js`
- `static/user/modules/views/preview-view.js`
- `static/user/modules/views/printing-view.js`
- `static/user/modules/views/done-view.js`
- `static/user/modules/shared/api.js`
- `static/user/modules/shared/runtime.js`
- `static/user/modules/shared/session-state.js`
- `static/user/modules/shared/toast.js`
- `static/user/modules/shared/dom.js`
- `static/user/modules/shared/capabilities.js`

其中：

- `app.js` 负责应用启动
- `app-state.js` 持有当前视图、会话、文件、打印状态
- `router.js` 只负责“内部视图切换”，不负责 URL 跳转
- `app-controller.js` 负责把视图行为、SSE 事件和 API 调用串起来
- `sse-client.js` 负责唯一的 `EventSource`
- `views/*` 负责各自视图的局部 DOM 渲染与事件绑定

### View Strategy

四个现有页面不会被拼成一个超长 HTML，而是保留为四个独立视图模块：

- `login`
- `preview`
- `printing`
- `done`

每个视图模块返回自己的局部模板，并在 `#app` 中渲染。视觉要求：

- 尽量复用现有文案、图片、类名、布局和交互节奏
- 不主动改变整体观感
- 允许对现有 DOM 结构做适度整理，使其更适合局部渲染

## State Model

应用级状态分三层：

### 1. UI 状态

- `currentView`
- `loading`
- `toast`
- `clock`

### 2. 交互会话状态

- `sessionId`
- `sessionPhase`
- `file`
- `options`
- `runtimeSettings`
- `capabilityState`
- `doneResult`

### 3. 实时连接状态

- `sse.connected`
- `sse.connecting`
- `sse.lastMessageAt`
- `sse.retryCount`

`sessionStorage` 仍然保留，但角色会变化：

- 从“页面切换的主要状态承载”降级为“刷新后的轻量恢复介质”
- 真正运行中的状态以 JS 内存中的应用级 store 为准

## Routing And Lifecycle

### Internal Navigation

以下跳转都改为内部路由切换：

- 扫码成功收到 `preview_file` 事件后：`login -> preview`
- 点击打印后：`preview -> printing`
- 收到打印完成或失败事件后：`printing -> done`
- 完成页倒计时结束或点击继续后：`done -> login`

这些切换不允许再使用：

- `window.location.href`
- `window.location.replace`
- 多 HTML 互跳

### SSE Lifecycle

SSE 改为应用级单例：

- 应用启动时初始化一次
- 视图切换时不关闭
- 仅在浏览器窗口关闭、刷新或应用主动销毁时关闭

前端的目标不是“绝对永不重连”，而是：

- 不再因为应用内部流程切换而断连
- 仅在真实网络中断、浏览器刷新、窗口关闭时才可能重连

这一定义与用户要求一致，因为“程序自身控制的切换”不会再触发连接抖动。

## Event Handling Model

应用级 SSE 只做一层分发：

- `preview_file`
- `job_status`
- `error`
- `cloud_error`
- 未来可扩展的 `node_status_changed`

处理原则：

- SSE 事件先进入 `app-controller`
- 由 controller 根据当前 `sessionId` 和 `sessionPhase` 决定是否接收
- 视图模块不直接持有 `EventSource`
- 视图只通过订阅状态更新来重渲染

## Backend Changes

### 1. 保留 `/api/events`，但补充稳定性 Header

`/api/events` 继续使用 SSE，不改协议方向，但应补充：

- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

目的是减少代理和浏览器层面对流式响应的干扰。

### 2. 新增当前交互会话快照接口

新增：

- `GET /api/session/current`

返回当前用户交互会话快照，最少包含：

- `active`
- `session_id`
- `state`
- `file_id`
- `file_url`
- `file_name`
- `file_type`
- `job_id`
- `submitted`

可选补充：

- `preview_ready`
- `printing`
- `completed`
- `failed`

用途：

- 浏览器刷新后恢复
- SSE 真断线后主动拉取兜底状态
- 应用启动时决定是否应直接回到 `preview` / `printing` / `done`

### 3. Session Manager 输出快照

`InteractiveSessionManager` 需要新增只读快照方法，例如：

- `build_snapshot()`

不改变现有会话状态机，只负责将内部会话映射为前端可消费的结构。

### 4. 可选的事件元数据

本次不强制实现完整事件回放，但建议为 SSE 消息增加：

- `event_id`
- `emitted_at`

即使前端暂时不使用，也为后续增强留出接口。

## Compatibility Strategy

为了避免已有入口失效，保留兼容层：

- `static/user/Index.html` 保留，但改为跳转到新的 `static/user/index.html`
- 旧的 `html/login.html`、`preview.html`、`printing.html`、`done.html` 可以保留为薄跳转页，统一重定向到 SPA 入口

这样：

- 旧书签和现有静态入口不会立即失效
- 真正业务运行仍由新 SPA 承载

## Testing Strategy

### Frontend Asset Tests

需要新增或调整静态结构测试，覆盖：

- `static/user/index.html` 存在 `#app`
- 用户端入口改为 `app.js`
- `main.js` 不再作为用户业务主入口
- `preview.js` / `printing.js` 中不再出现 `window.location.href`
- 只存在一个应用级 SSE 客户端模块

### Backend Tests

需要新增测试覆盖：

- `/api/session/current` 在无会话时返回 `active = false`
- 预览事件绑定后，快照返回 `preview_ready`
- 提交打印后，快照返回 `print_submitted` 或 `printing`
- 打印完成后，快照返回 `completed`

### Behavioral Verification

至少验证以下行为：

1. 打开用户端页面时，后端 `/api/events` 连接数增加到 1
2. 从二维码页进入预览页时，连接数不变化
3. 从预览页进入打印中页时，连接数不变化
4. 从完成页回到二维码页时，连接数不变化
5. 关闭页面后，连接数变为 0
6. 正常流程中，前端不再因为视图切换重建 `EventSource`
7. 浏览器刷新后，可通过快照恢复到合理页面

## Risks And Mitigations

### Risk 1: 视图模块化后 DOM 结构漂移

风险：

- 为了改成局部渲染，可能不小心改变现有布局和样式挂载方式

缓解：

- 以“视觉不变”为约束
- 优先复用现有 CSS、图片和文案
- 每个视图独立回归检查

### Risk 2: 单例 SSE 与状态机耦合过深

风险：

- 如果把所有事件处理都写进一个大文件，新的 SPA 会重新变成不可维护的大脚本

缓解：

- SSE 只负责连接与分发
- Controller 负责流程编排
- View 只负责渲染和 UI 事件

### Risk 3: 浏览器真实断线后的恢复不一致

风险：

- 单靠前端内存状态无法应对刷新或网络闪断

缓解：

- 增加 `/api/session/current`
- 应用启动和 SSE 异常恢复时主动拉快照

## Rollout Plan

建议顺序：

1. 先补静态测试，锁定 SPA 壳与无跳页约束
2. 建立 `user` 端单入口壳和应用级状态/路由骨架
3. 迁移四个页面为四个视图模块
4. 将 SSE 提升为应用级单例
5. 去掉所有用户流程中的整页跳转
6. 后端补会话快照接口
7. 补充回归测试与连接稳定性验证

## Acceptance Criteria

- `user` 端运行于单一 HTML 入口，不再依赖四个业务 HTML 互跳
- 二维码、预览、打印中、完成均在单一浏览器上下文内完成
- 应用内部视图切换不会导致 `/api/events` 断开重连
- 后端新增当前交互会话快照接口
- 浏览器刷新后，前端能够恢复到合理流程位置
- 整体视觉与现有版本保持一致或仅有极小结构性调整
