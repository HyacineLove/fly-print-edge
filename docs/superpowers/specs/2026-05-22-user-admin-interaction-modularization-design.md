# User And Admin Interaction Modularization Design

**Date:** 2026-05-22

## Goal

本期在不引入构建工具的前提下，同时完成两件事：

- 先把用户端与管理端当前过大的 `main.js` 拆成可维护的原生模块结构
- 再在新结构上完成二维码页、预览页、管理端的一批交互优化

本次重点不是重做视觉系统，而是在保留现有页面主体结构和接口契约的基础上，补齐提示、加载、禁用、能力展示与可维护性。

## Non-Goals

- 不引入 Webpack、Vite、Rollup 等构建工具
- 不改造云端协议和打印任务主链路
- 不重做整套管理端 UI 风格
- 不新增复杂的前端状态管理框架
- 不顺手做与本次需求无关的大规模重构

## Current State

### User Side

当前用户端核心脚本集中在：

- `static/user/main.js`

这个文件同时承担了：

- 二维码页初始化
- 预览页初始化
- 打印中页逻辑
- 完成页逻辑
- 状态存储
- 请求封装
- 倒计时
- 预览刷新
- 能力禁用

这导致后续每次改动都需要在单个超大文件里同时理解多页逻辑，维护成本已经明显偏高。

### Admin Side

当前管理端核心脚本集中在：

- `static/admin/main.js`

这个文件同时承担了：

- 配置页状态管理
- 配置保存
- 云端检测与注册
- 打印机列表加载
- 列表渲染
- 表单编辑
- 按钮状态切换

随着配置项和打印机交互继续增加，单文件继续膨胀的风险很高。

### UX Gaps

本次用户反馈集中暴露出以下问题：

- 二维码页把正常状态也长期显示在页面中部，信息噪音偏高
- 二维码未加载成功时，中间小图标仍显示，视觉上像“假成功”
- 预览页份数按钮的形态与其他选项区块不统一
- 管理端部分过程没有明确提示，用户难以判断“是否正在执行”
- 管理端加载期间仍可继续交互，容易造成重复操作
- 打印机管理缺乏能力摘要，用户无法快速判断单双面和彩色支持情况

## Product Direction

采用“模块拆分优先 + 交互定点增强”的方案。

即：

1. 先把两个 `main.js` 改成原生 `ES Module` 入口
2. 按页面和职责拆分为多个小模块
3. 在新模块结构上实现交互优化

这样可以避免先在旧大文件上改一轮，再为了维护性重复拆分一轮。

## Frontend Module Design

### Module Loading Strategy

不引入构建工具，直接使用浏览器原生模块能力：

- HTML 使用 `type="module"` 引入单个入口脚本
- 入口脚本按职责 `import` 其他模块
- 保持部署方式与当前静态资源目录结构兼容

不采用“多个普通 script 顺序拼接全局变量”的方式，因为那种方式短期能拆文件，但长期仍容易出现依赖顺序和命名污染问题。

### User Side Module Split

用户端建议拆分为以下结构：

- `static/user/main.js`
  - 仅作为模块入口，按 `body[data-page]` 分发到具体页面
- `static/user/modules/shared/api.js`
  - `getJson`、`postJson`、接口路径常量
- `static/user/modules/shared/session-state.js`
  - `sessionStorage` 状态读写、默认值、归一化
- `static/user/modules/shared/toast.js`
  - 顶部 toast 的显示、隐藏、样式切换
- `static/user/modules/shared/clock.js`
  - 时钟与通用倒计时显示
- `static/user/modules/shared/touch-guard.js`
  - 现有触控限制逻辑
- `static/user/modules/shared/capabilities.js`
  - 打印机能力解析、单双面/彩色支持判断、禁用状态推导
- `static/user/modules/pages/login.js`
  - 二维码页逻辑
- `static/user/modules/pages/preview.js`
  - 预览页逻辑
- `static/user/modules/pages/printing.js`
  - 打印中页逻辑
- `static/user/modules/pages/done.js`
  - 完成页逻辑

其中：

- login / preview 不再互相夹杂具体页面行为
- 能力解析与份数范围逻辑从页面脚本中抽离
- toast 作为用户端统一提示机制，由各页复用

### Admin Side Module Split

管理端建议拆分为以下结构：

- `static/admin/main.js`
  - 仅作为模块入口，启动管理端应用
- `static/admin/modules/api.js`
  - 管理端请求封装
- `static/admin/modules/state.js`
  - 页面状态、脏数据判断、待处理动作集合
- `static/admin/modules/toast.js`
  - 顶部 toast 逻辑
- `static/admin/modules/loading-overlay.js`
  - 全页 loading 遮罩的显示与隐藏
- `static/admin/modules/render-sections.js`
  - 各分区 HTML 渲染
- `static/admin/modules/config-actions.js`
  - 保存配置、检测注册等配置相关动作
- `static/admin/modules/printer-actions.js`
  - 打印机刷新、添加、删除、设默认、重注册
- `static/admin/modules/printer-capabilities.js`
  - 打印机能力文案整理和展示辅助

这样拆分后：

- “渲染”
- “网络请求”
- “动作处理”
- “全局提示”
- “全局加载”

这几类职责能明确分开，后续继续加功能时不容易重新堆回一个大文件。

## User UX Design

### Login / QR Page

页面目标改为“默认安静，只有需要用户感知的过程才提示”。

#### Normal State

删除二维码与“刷新二维码”按钮之间的常驻提示文案。

也就是说：

- 不再在页面中部长期显示“已连接到云端服务器”
- 正常加载成功后，页面保持安静

#### Loading And Error Feedback

以下场景统一使用顶部 toast：

- 获取二维码中
- 获取二维码失败
- 云端异常
- 二维码返回 standby 或其他不可用状态

其中“初始化获取二维码”和“手动刷新二维码”统一使用同一条文案：

- `获取二维码中`

不区分用户是自动进入页面、倒计时刷新还是手动点击刷新。

#### QR Inner Icon Visibility

当二维码尚未成功加载出来时：

- 隐藏二维码中央小图标
- 隐藏中间底板

只有在拿到有效二维码图片并完成渲染后，才显示中间小图标与底板。

这样可以避免失败态或加载态仍看起来像“二维码已经准备好了”。

### Preview Page

#### Copies Control

份数控件从：

- `- / 当前值 / +`

调整为：

- 左三角 / 当前值 / 右三角

三列区域要求：

- 三个小方格等宽
- 三个小方格垂直对齐
- 份数区与单双面、彩色黑白区块在横向栅格上尽量统一

交互规则保持现有确认结果：

- 份数范围由管理侧 `copies_min / copies_max` 决定
- 份数变化只重置倒计时
- 份数变化不刷新预览
- 到达上下限时对应方向按钮置灰禁用

#### Duplex Control

单双面区保留当前语义：

- `单面`
- `双面`

交互规则保持：

- 不支持双面时显示但置灰禁用
- 若当前值非法，自动回退到单面
- 切换单双面只重置倒计时，不刷新预览

#### Color Control

彩色区保留当前语义：

- `黑白`
- `彩色`

交互规则保持：

- 不支持彩色时显示但置灰禁用
- 若当前值非法，自动回退到黑白
- 切换彩色黑白会刷新预览

### User Toast Pattern

用户端新增统一顶部 toast 容器，视觉方向参考用户提供的示例图：

- 顶部悬浮
- 白色底卡片
- 轻阴影
- 成功 / 信息 / 错误用不同图标或颜色点缀

本期 toast 主要承接：

- 获取二维码中
- 获取二维码失败
- 云端错误
- 其他必须即时告知用户的异常

正常成功不强制弹 toast。

## Admin UX Design

### Navigation Simplification

左侧导航删除：

- `概览`
- `打印机发现`

保留：

- `云端配置`
- `打印默认设置`
- `运行设置`
- `打印机管理`

删除后不再渲染对应内容区块，也不保留仅隐藏的旧入口，避免后续逻辑继续依赖已废弃 section。

### Global Loading Overlay

管理端增加统一全页 loading 遮罩，用于阻止交互并明确告知“操作正在进行”。

以下场景启用：

- 页面首次加载
- 保存配置
- 检测连接并注册节点
- 刷新打印机管理列表

遮罩层覆盖整个管理页，至少包含：

- 半透明遮罩
- `加载中...` 文案

目标是避免：

- 用户重复点击
- 在旧数据还没刷新时继续操作

### Config Action Feedback

#### Save Config

“保存配置”按钮行为调整为：

- 按钮文字保持 `保存配置`
- 执行中按钮禁用并置灰
- 用顶部 toast 提示：
  - `保存配置中`
  - `配置已保存`
  - `保存配置失败`

不再用按钮文案切换为“保存中...”。

#### Check And Register

“检测连接并注册节点”按钮行为调整为：

- 按钮文字保持不变
- 执行中按钮禁用并置灰
- 用顶部 toast 提示：
  - `检测连接中`
  - `检测并注册完成`
  - `检测连接失败`

同样不再修改按钮内部文案。

### Printer Management

#### Refresh Button

打印机管理区只保留一个刷新按钮：

- `刷新`

移除现有三个按钮：

- `刷新全部`
- `刷新已管理`
- `刷新可添加`

点击刷新后：

- 显示顶部 toast，例如 `刷新打印机列表中`
- 启用全页 loading 遮罩
- 完成后刷新“已管理打印机”和“可添加打印机”两块数据

#### Printer Capability Display

打印机管理新增“能力”展示列。

能力展示不直接暴露原始复杂 capability 结构，而是显示简化摘要，例如：

- `单双面: 支持, 彩色: 支持`
- `单双面: 不支持, 彩色: 支持`
- `单双面: 未知, 彩色: 未知`

能力未知时必须明确显示“未知”，不要默认伪装成“不支持”。

## Backend Design

### Admin Printer Capability Summary

为了支持管理端能力展示，后端在管理端打印机接口中补充统一摘要字段。

优先改造：

- `GET /api/admin/printers/managed`
- `GET /api/admin/printers/discovered`

建议每个打印机返回：

- `duplex_supported`
- `color_supported`
- `capability_summary`

其中：

- `duplex_supported` 允许为 `true / false / null`
- `color_supported` 允许为 `true / false / null`
- `null` 表示未知

`capability_summary` 由后端直接产出最终展示文案，避免前端散落多套解析规则。

### Capability Interpretation Rules

能力解析沿用用户端已建立的基本规则，但管理端采用“三态”：

- 明确支持
- 明确不支持
- 未知

解析建议：

- `duplex` 中存在明确双面能力值则记为支持
- `duplex` 明确只包含单面或 `none` 则记为不支持
- 缺失、空值、格式异常则记为未知

- `color_model` 中存在 `RGB`、`Color`、`Colour` 等彩色值则记为支持
- 明确仅有 `Gray`、`Mono` 等黑白值则记为不支持
- 缺失、空值、格式异常则记为未知

### User APIs

用户端接口不新增新的独立配置接口。

继续沿用现有：

- `/api/qr_code`
- `/api/preview`
- `/api/print`

本期只调整前端对这些接口结果的交互映射方式。

## HTML / CSS Design Notes

### User HTML

用户端页面需要新增 toast 容器占位，并将脚本改为模块入口加载。

预览页需要：

- 更新份数按钮文本或图形元素为左右三角
- 保留现有可点击热区 id 或提供稳定的新选择器

登录页需要：

- 为二维码中间图标与底板提供可单独控制显隐的选择器

### Admin HTML

管理端页面需要：

- 新增 toast 容器
- 新增 loading overlay 容器
- 调整导航项
- 让打印机管理 toolbar 仅保留单个刷新按钮
- 脚本改为模块入口加载

### Styling Direction

本期视觉方向保持现有风格，仅做增强：

- toast 使用轻浮层卡片样式
- loading 使用遮罩 + 居中文案
- 份数三角按钮与其他两组按钮统一边框、圆角、居中对齐
- 禁用态统一使用浅灰 + 降低不透明度 + 禁止指针事件

## Testing Strategy

### Static Asset Tests

新增或更新测试，覆盖：

- 用户端和管理端改为模块入口加载
- 登录页不再依赖中部常驻状态文案
- 登录页存在顶部 toast 容器
- 预览页份数按钮使用左右三角
- 管理端导航移除“概览”和“打印机发现”
- 打印机管理仅保留一个刷新按钮
- 管理端存在 loading overlay 容器

### Backend Tests

新增或更新测试，覆盖：

- 管理端打印机接口返回能力摘要字段
- 能力明确支持时布尔值和文案正确
- 能力明确不支持时布尔值和文案正确
- 能力未知时返回 `null` 与“未知”摘要

### Behavior Verification

回归验证至少覆盖：

1. 用户端进入二维码页时 toast 显示“获取二维码中”
2. 二维码获取成功后中部常驻提示不再显示
3. 二维码失败时顶部 toast 给出错误反馈，且中间图标隐藏
4. 预览页份数按钮三列对齐，左右三角可用
5. 份数变化不刷新预览
6. 单双面变化不刷新预览
7. 彩色变化刷新预览
8. 管理端首次加载时出现全页 loading
9. 保存配置时按钮禁用、toast 提示正确
10. 检测注册时按钮禁用、toast 提示正确
11. 打印机管理点击刷新时出现 toast 和 loading
12. 打印机管理能力列展示正确

## Risks And Mitigations

### Risk 1: Module Split Breaks Existing Page Bootstrapping

原先所有逻辑集中在一个文件里，拆分后最容易出问题的是页面入口没有正确初始化。

缓解方式：

- 保留单一 `main.js` 作为入口，不让 HTML 直接感知过多内部模块
- 每个页面入口只初始化自己负责的页面
- 通过静态测试和手动验证确保四个页面都能正常启动

### Risk 2: Toast And Loading Logic Diverge Between User And Admin

如果用户端和管理端各写一套完全随意的提示逻辑，后续仍会继续分散。

缓解方式：

- 两端各自内部统一一个 toast 模块
- 两端各自内部统一一个 loading 模块或封装方式
- 不跨端强行共享文件，但保持模式一致

### Risk 3: Capability Parsing In Admin And User Becomes Inconsistent

用户端已经有能力禁用规则，管理端如果再写一套不同判断，容易出现“用户端禁用但管理端显示支持”的不一致。

缓解方式：

- 后端统一整理管理端能力摘要
- 用户端保留交互级判断
- 测试中覆盖典型 capability 输入

## Rollout Plan

建议按以下顺序实施：

1. 完成用户端和管理端入口模块化拆分
2. 保证拆分后现有功能不回退
3. 接入用户端 toast 与二维码页状态收敛
4. 调整预览页份数控件样式
5. 接入管理端 toast 与全页 loading
6. 简化管理端导航与打印机刷新交互
7. 补后端打印机能力摘要字段
8. 补测试并做回归验证

## Acceptance Criteria

- 用户端与管理端不再依赖单个超大 `main.js` 承载全部逻辑
- 前端模块化不依赖构建工具，直接通过原生模块运行
- 二维码页删除中部常驻正常提示
- “获取二维码中”统一作为二维码加载过程提示文案
- 二维码未成功加载时，中间小图标与底板隐藏
- 预览页份数按钮改为左右三角，并与其他选项区块尽量对齐
- 管理端删除“概览”和“打印机发现”
- 管理端在首次加载、保存、检测注册、刷新打印机时提供明显反馈
- “保存配置”和“检测连接并注册节点”执行中按钮文字保持不变，仅禁用置灰
- 打印机管理只保留单个“刷新”按钮
- 管理端可展示打印机能力摘要
