# User Preview Copies And Capability Gating Design

**Date:** 2026-05-22

## Goal

为本地用户侧参数选择与预览页面补齐两类能力：

- 将“打印份数”从固定的 `1/2/3` 三档改为管理侧可配置的全局上下限，并在用户侧通过增减按钮驱动
- 让用户侧“单面/双面”和“彩色/黑白”按照默认打印机能力做禁用控制，避免用户选择打印机不支持的能力

## Non-Goals

- 本期不引入按打印机分别配置打印份数上下限的能力
- 本期不新增用户侧手动输入份数，份数仅通过增减按钮调整
- 本期不改动云端协议字段结构
- 本期不新增真正的“纵向/横向”页面方向能力；当前页面实际涉及的是“单面/双面”和“彩色/黑白”

## Current State

### User Preview Page

当前用户侧预览页位于：

- `static/user/html/preview.html`
- `static/user/main.js`
- `static/user/css/preview.css`

现状如下：

- 打印份数是写死的 `1`、`2`、`3` 三档按钮
- 份数切换会刷新预览
- “打印模式”实际是 `simplex` 与 `longedge`，也就是单面与双面
- “色彩选择”实际是 `color` 与 `mono`
- 页面已能从 `/api/qr_code` 返回值中拿到 `default_printer_capabilities`

### Capability Gating

当前前端已有一个 `updateCapabilityUi(capabilities)`，但行为较弱：

- 只在部分文案上做了透明度处理
- 没有形成完整的禁用态
- 没有对交互点击进行彻底阻断
- 没有统一的“能力应用后重新夹紧状态”逻辑

### Admin Config Center

当前管理侧配置中心位于：

- `static/admin/html/index.html`
- `static/admin/main.js`
- `static/admin/css/admin.css`

配置以 `settings`、`cloud`、`network`、`printers` 等分组进行维护。打印默认设置已经是全局打印行为配置的集中入口，因此本期的份数上下限应落在 `settings` 组中。

## Product Direction

采用一套全局打印份数范围配置，所有打印机共用：

- `settings.copies_min`
- `settings.copies_max`

用户侧不再显示固定三档份数按钮，而是改为：

- `-` 按钮
- 当前份数值
- `+` 按钮

默认打印机能力禁用规则以“保守允许”为原则：

- 单面始终允许
- 黑白始终允许
- 双面仅在默认打印机明确支持双面时允许
- 彩色仅在默认打印机明确支持彩色时允许

## Config Model

### New Settings Fields

在 `settings` 中新增两个全局字段：

- `copies_min`: 最小打印份数
- `copies_max`: 最大打印份数

默认值建议为：

- `copies_min = 1`
- `copies_max = 3`

这样可以与当前用户侧默认体验保持接近，同时支持后续在管理侧放宽或收紧范围。

### Validation Rules

管理侧保存配置时执行如下校验：

- `copies_min` 必须为整数
- `copies_max` 必须为整数
- `copies_min >= 1`
- `copies_max >= copies_min`

如果校验失败，则阻止保存，并向管理侧返回清晰错误信息。

## Admin UX Design

### Placement

在“打印默认设置”分组新增两个数字输入项：

- 最小打印份数
- 最大打印份数

这两个字段与现有的默认纸张、默认缩放、最大放大倍数并列展示，因为它们同样属于全局打印默认行为配置。

### Save Behavior

管理侧“保存配置”时：

- 将 `copies_min` 与 `copies_max` 一并写入 `/api/admin/config`
- 后端统一完成字段校验与持久化
- 保存成功后继续走当前配置中心的统一反馈机制

### Validation Feedback

当份数配置非法时，错误信息应聚焦到业务语义：

- `settings.copies_min must be an integer >= 1`
- `settings.copies_max must be an integer and >= settings.copies_min`

如果后端当前校验风格偏中文，可转成等价中文错误：

- `最小打印份数必须为大于等于 1 的整数`
- `最大打印份数必须为大于等于最小打印份数的整数`

## User Preview UX Design

### Copies Control

用户侧将现有固定三档份数区域改造成三段式控件：

- 左侧为减号按钮
- 中间为当前份数文本
- 右侧为加号按钮

交互规则如下：

- 初始值以 `1` 为基础值
- 初始值会被夹紧到 `[copies_min, copies_max]`
- 点击 `-` 时，份数减 `1`
- 点击 `+` 时，份数加 `1`
- 达到最小值后，`-` 按钮置灰禁用
- 达到最大值后，`+` 按钮置灰禁用
- 份数变化后不刷新预览
- 份数变化后只重置倒计时并更新 UI

### Duplex Control

当前页面中的“打印模式”实际表示单面与双面：

- 单面: `simplex`
- 双面: `longedge`

交互规则如下：

- 如果默认打印机不支持双面，则“双面”按钮置灰禁用
- 若当前值为双面，能力应用时自动切回 `simplex`
- 单面保持可选
- 单双面变化后不刷新预览
- 单双面变化后只重置倒计时并更新 UI

之所以不刷新预览，是因为单双面不会改变单页预览的视觉结果。

### Color Control

“色彩选择”保留彩色与黑白两个选项：

- 彩色: `color`
- 黑白: `mono`

交互规则如下：

- 如果默认打印机不支持彩色，则“彩色”按钮置灰禁用
- 若当前值为彩色，能力应用时自动切回 `mono`
- 黑白保持可选
- 彩色黑白变化后重置倒计时
- 彩色黑白变化后继续刷新预览

之所以保留彩色切换触发预览刷新，是因为预览图像可能受颜色模式影响。

### Disabled State

不支持的选项不隐藏，只置灰禁用。禁用态应同时覆盖视觉和交互：

- 背景改为浅灰
- 文字改为浅灰
- 透明度降低
- `pointer-events: none`
- 鼠标样式改为 `not-allowed` 或等效禁用样式

禁用态必须作用在整个按钮热区，而不只是标签文本，避免出现“看起来灰了但还能点击”的情况。

## Data Flow

### Config Delivery

用户侧需要在初始化阶段拿到两类信息：

- 全局份数范围配置 `copies_min` / `copies_max`
- 默认打印机能力 `default_printer_capabilities`

推荐做法是沿用当前 `/api/qr_code` 的初始化负载，在其中补充可公开的打印设置字段，例如：

- `settings.copies_min`
- `settings.copies_max`

这样用户侧无需额外发起一条配置请求，初始化路径保持集中。

### Initialization Order

预览页初始化顺序调整为：

1. 读取后端下发的全局打印设置与默认打印机能力
2. 构造默认 `state.options`
3. 用份数范围夹紧 `state.options.copies`
4. 用打印机能力修正 `duplex` 与 `color_mode`
5. 渲染 UI
6. 请求首张预览图

这样可以避免首屏先显示一个不可用选项，再被脚本切回的闪动。

## Backend Design

### Config Persistence

后端配置模型需支持：

- 加载缺省 `copies_min` / `copies_max`
- 对旧版 `config.json` 做向后兼容
- 在 `get_public_config()` 中公开这两个安全字段

如果旧配置中缺失该字段，后端应自动补默认值 `1` 和 `3`，避免老环境升级后出现空值。

### Print Submission Guard

打印提交时后端必须再次校验 `options.copies`，不能只依赖前端约束。

建议采取“夹紧”策略而不是直接报错：

- 若 `copies < copies_min`，按 `copies_min` 处理
- 若 `copies > copies_max`，按 `copies_max` 处理

这样可以覆盖以下场景：

- 用户侧状态偶发不同步
- 有人绕过前端直接调用 `/api/print`
- 边界配置更新后，旧页面仍在提交旧值

### Capability Interpretation

默认打印机能力解释规则如下：

- 双面支持：`capabilities.duplex` 中只要存在非 `None` 的有效双面值，即视为支持双面
- 彩色支持：`capabilities.color_model` 中只要存在 `RGB`、`Color` 或等价彩色值，即视为支持彩色

如果能力字段缺失、为空或解析失败，则采取保守回退：

- 允许单面
- 允许黑白
- 禁用双面
- 禁用彩色

## Frontend Implementation Notes

### State Helpers

建议在用户侧新增两个职责清晰的辅助层：

- 份数范围解析与夹紧函数
- 打印能力归一化与禁用函数

前者负责：

- 读取并规范化 `copies_min` / `copies_max`
- 保证最小值至少为 `1`
- 保证最大值不小于最小值
- 对 `state.options.copies` 做夹紧

后者负责：

- 从原始 `default_printer_capabilities` 推导 `duplexSupported`、`colorSupported`
- 在能力不支持时修正当前状态
- 输出 UI 禁用态所需布尔值

### Preview Refresh Policy

本期预览刷新策略应显式固定为：

- 份数变化：不刷新预览
- 单双面变化：不刷新预览
- 彩色黑白变化：刷新预览

这条规则需要集中在事件处理层，避免后续某个分支意外重新把份数或单双面绑定到预览刷新。

## Testing Strategy

### Admin Tests

需要覆盖：

- `copies_min = 1, copies_max = 1` 可保存
- `copies_min = 2, copies_max = 5` 可保存
- `copies_min > copies_max` 保存失败
- `copies_min < 1` 保存失败
- 缺失字段时自动回落到默认值

### User Flow Tests

需要覆盖：

- 进入预览页时，份数会被夹紧到配置范围内
- 最小值边界时减号按钮禁用
- 最大值边界时加号按钮禁用
- 点击减号或加号只更新份数和倒计时，不发起预览请求
- 点击单双面只更新状态和倒计时，不发起预览请求
- 点击彩色黑白会发起预览请求
- 默认打印机不支持双面时，“双面”置灰禁用并自动切回单面
- 默认打印机不支持彩色时，“彩色”置灰禁用并自动切回黑白

### Backend Tests

需要覆盖：

- `/api/print` 收到越界 `copies` 时会按范围夹紧
- 旧版配置未包含份数字段时，打印接口仍能按默认范围工作
- 公开配置接口会返回 `copies_min` / `copies_max`

## Risks And Mitigations

### Risk 1: Old Sessions Submit Stale Copy Counts

用户可能在配置更新前打开页面，并在配置更新后继续提交旧份数。

缓解方式：

- 打印接口做后端夹紧
- 用户侧每次初始化都从最新公共配置取份数范围

### Risk 2: Capability Payload Shape Is Inconsistent

不同平台解析出的 `duplex` 或 `color_model` 可能是列表、字符串或其他结构。

缓解方式：

- 前端能力解析统一先做字符串归一化
- 必要时后端进一步规范 `default_printer_capabilities` 的输出形态

### Risk 3: Disabled Styling Is Incomplete

如果只把文字调淡，不会形成明确的不可点击反馈。

缓解方式：

- 禁用态同时控制背景、文字、透明度、指针事件和鼠标样式
- 事件处理层也要做兜底拦截

## Rollout Plan

建议按以下顺序实施：

1. 扩展配置模型与默认值
2. 扩展管理侧表单与保存校验
3. 扩展 `/api/qr_code` 或等价初始化负载，向用户侧下发份数范围
4. 重构用户侧份数控件与能力禁用逻辑
5. 为打印提交补后端夹紧
6. 补充针对配置边界和交互边界的测试

## Acceptance Criteria

- 管理侧可配置并保存全局最小打印份数与最大打印份数
- 用户侧份数控件改为 `- / 当前值 / +`
- 用户侧份数不能超出管理侧配置范围
- 份数变化不会触发预览刷新，只会重置倒计时
- 单双面变化不会触发预览刷新，只会重置倒计时
- 彩色黑白变化会触发预览刷新
- 默认打印机不支持双面时，“双面”显示为置灰禁用
- 默认打印机不支持彩色时，“彩色”显示为置灰禁用
- 后端打印接口对越界份数有兜底处理
