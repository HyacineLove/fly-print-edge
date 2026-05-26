# Runtime Log Optimization Design

**Date:** 2026-05-22

## Goal

整理 Edge 端运行时日志，让默认运行模式更安静、更适合值守，同时保留一键切换到详细调试日志的能力，降低排障成本并减少控制台噪音。

本次设计的重点不是“增加更多日志”，而是：

- 统一日志出口和级别控制
- 压缩高频成功日志
- 保留关键节点与异常
- 提供默认简洁、按需详细的双模式

## Non-Goals

- 不改动二维码、预览、打印、管理端的业务行为
- 不改变现有接口契约或前端交互
- 不引入外部日志平台、日志采集 agent 或 JSON logging 基础设施
- 不在本次引入完整 request id / trace id / session id 全链路结构化追踪
- 不调整打印任务成功/失败的判定策略

## Current Problems

### 1. 日志出口不统一

当前代码混用了两类输出方式：

- `logging` 模块，如 `main.py` 中的 `logger.info(...)`
- 大量 `print(...)`

同时很多 `print(...)` 自己拼接了 `[DEBUG]`、`[INFO]`、`[WARNING]` 前缀，导致“日志级别”只是字符串，不是真正可配置的 logging level。

### 2. 高频成功日志过多

以下链路存在明显的逐步展开日志：

- `/api/preview` 预览生成
- 预览文件下载
- SSE 建连与断连
- WebSocket 心跳
- 打印队列轮询
- 文件清理与缓存清理

这些日志在排障时有帮助，但默认运行时会淹没真正重要的信息。

### 3. 同一事件被拆成过多行

例如一次预览文件下载会输出：

- 开始下载
- file_url
- file_name
- file_id
- 获取认证头
- token 来源
- headers
- 最终 URL
- 扩展名
- 临时路径
- 发起请求
- 响应状态
- 写入文件
- 下载成功

单个事件需要跨十几行才能看完整，阅读成本高。

### 4. 成功日志与异常日志层级不平衡

当前大量正常成功路径在 `INFO` 或伪 `DEBUG` 层级持续输出，但部分真正重要的异常上下文又不够集中。结果是：

- 平时看日志太吵
- 真出问题时不容易快速定位主线

### 5. 默认模式与排障模式没有明确切换机制

当前运行时没有稳定、统一的日志级别入口。虽然部分日志写成了 `[DEBUG]`，但它们仍然会无条件打印，无法做到：

- 默认值守模式安静
- 需要时一键打开详细过程日志

## Design Principles

### 默认值班友好

默认模式面向“服务正在跑，想快速看健康状态与关键业务节点”的场景，只保留高信号日志。

### 调试模式完整可追

调试模式面向“正在定位问题”的场景，保留详细过程日志，但也要避免无限制刷屏；轮询类日志只在状态变化或关键采样点输出。

### 统一由 logging 控制

日志级别必须由标准 `logging` 统一控制，不再依赖手写字符串前缀表达日志等级。

### 保持改动渐进

优先整理后端运行时主链路：

- `main.py`
- `cloud_websocket_client.py`
- `file_manager.py`
- `printer_utils.py`
- `printer_config.py`

不在本次顺手重构所有架构层次。

## Proposed Architecture

### 1. 新增统一日志配置入口

新增一个集中初始化 logging 的模块，例如：

- `logging_utils.py`

负责：

- 读取配置文件中的 `settings.log_level`
- 读取配置文件中的 `settings.debug_logging`
- 读取环境变量 `FLYPRINT_LOG_LEVEL`
- 读取环境变量 `FLYPRINT_DEBUG_LOGGING`
- 按优先级计算最终级别
- 初始化根 logger 和 formatter

优先级：

1. 环境变量
2. 配置文件
3. 默认值

默认值建议：

- `log_level = INFO`
- `debug_logging = false`

当 `debug_logging = true` 且未显式设置更低级别时，最终级别提升为 `DEBUG`。

### 2. 模块级 logger 统一替代 print

为主要后端模块增加模块级 logger，例如：

```python
import logging

logger = logging.getLogger(__name__)
```

然后将现有 `print(...)` 迁移为：

- `logger.debug(...)`
- `logger.info(...)`
- `logger.warning(...)`
- `logger.error(...)`
- `logger.exception(...)`

迁移原则：

- 不再手写 `[DEBUG]`、`[INFO]` 字符串前缀
- formatter 统一输出时间、模块名、级别与消息

### 3. 日志分层规则

#### 默认保留为 INFO

- 服务启动/停止
- 云端 WebSocket 连接成功、断开、重连等待
- 收到预览任务
- 收到打印任务
- 打印任务提交成功
- 打印任务最终完成/失败
- 批量清理摘要
- 重要配置加载结果

#### 降级为 DEBUG

- `/api/preview` 逐步处理细节
- 预览下载 URL、headers、临时路径
- SSE 每次建连/断连
- 心跳成功
- 缓存命中细节
- token 存取细节
- 文件注册与单文件删除
- 打印队列轮询中间态
- 打印机发现过程细节
- 配置文件保存的逐步细节

#### 保持 WARNING / ERROR

- 缺 token
- 文件下载失败
- WebSocket 异常
- 轮询超时
- 打印状态查询异常
- 文件删除失败
- 配置加载/保存失败

### 4. 多行日志合并策略

对以下场景进行合并：

#### 预览下载

默认模式：

- `开始处理预览请求: file_id=..., page_index=...`
- `预览文件下载成功: file_id=..., ext=.jpg, size=..., source=token`

调试模式才输出：

- 下载 URL 来源
- headers
- 临时路径
- 缓存命中/未命中

#### 打印文件下载

默认模式：

- `下载打印文件: job_id=..., auth=file_access_token`
- `打印文件下载成功: job_id=..., ext=.pdf`

调试模式才输出完整 URL、临时路径与响应细节。

#### 文件清理

默认模式：

- `清理过期预览资源: count=3`
- `清理过期 token: count=2`
- `释放打印临时文件: job_id=...`

调试模式才输出单个文件路径与每一步释放细节。

### 5. 轮询与心跳的降噪规则

#### 打印队列轮询

默认模式：

- 仅输出进入轮询、轮询完成、轮询超时、轮询失败

调试模式：

- 仅在状态变化时输出，如“队列任务数变化”“任务状态变化”
- 不再每 1 秒无条件刷一行相同内容

#### WebSocket 心跳

默认模式：

- 不输出“心跳发送成功”

调试模式：

- 保留心跳成功日志

### 6. SSE 日志调整

SSE 建连/断连对排障有价值，但默认太吵。调整为：

- 默认模式：`DEBUG`
- 如果发生 SSE 推送失败，升为 `ERROR`
- 如果前端消息被丢弃且影响业务判断，可保留单条 `INFO/WARNING`

## Configuration Changes

配置文件建议新增字段：

```json
{
  "settings": {
    "log_level": "INFO",
    "debug_logging": false
  }
}
```

约束：

- `settings.log_level` 允许值：`DEBUG`、`INFO`、`WARNING`、`ERROR`
- `settings.debug_logging` 为布尔值

环境变量：

- `FLYPRINT_LOG_LEVEL`
- `FLYPRINT_DEBUG_LOGGING`

规则：

- 如果环境变量存在，覆盖配置文件
- 如果 `debug_logging=true` 且 `log_level` 未明确设置为更高阈值，则允许启用详细调试输出

## File-Level Change Plan

### `logging_utils.py`

新增统一 logging 初始化与配置解析函数。

### `main.py`

- 在启动最早阶段调用日志初始化
- 将预览请求、大段下载调试、SSE 连接日志迁移为标准 logger
- 保留服务生命周期与关键业务节点 `INFO`

### `cloud_websocket_client.py`

- 将 WebSocket 生命周期、上传凭证、预览任务、打印任务日志分层
- 收敛下载打印文件与打印任务监控日志

### `file_manager.py`

- 保留初始化、过期清理摘要、严重失败
- 将单文件注册/释放细节降到 `DEBUG`

### `printer_utils.py`

- 打印机发现过程、轮询细节改为 `DEBUG`
- 提交打印与最终清理结果保留为 `INFO`

### `printer_config.py`

- 配置文件读取/保存的逐步过程改为 `DEBUG`
- 真正异常保留为 `ERROR/WARNING`

### `config_service.py`

- 仅在新增日志配置校验或公开配置构建时做最小接入

## Testing Strategy

### 单元测试

新增围绕日志配置的测试，覆盖：

- 默认配置落到 `INFO`
- 配置文件 `log_level` 生效
- 环境变量优先级高于配置文件
- `debug_logging=true` 时可启用 `DEBUG`
- 非法 `log_level` 回退默认值或被规范化

### 运行时冒烟验证

至少验证两组场景：

#### 默认模式

- 启动服务
- 扫码上传 -> 预览 -> 打印 -> 完成
- 确认日志显著少于当前版本，主链路可读

#### 调试模式

- 通过环境变量开启详细日志
- 重跑同一流程
- 确认详细日志出现，且没有恢复到“每一步都十几行”的失控状态

### 回归测试

必须继续通过现有 pytest 全量测试，确保本次只是日志行为优化，不影响业务逻辑。

## Risks And Mitigations

### 风险 1：降噪过度，排障信息不够

缓解：

- 不删除关键上下文，只调整级别和合并方式
- 默认模式变少，调试模式保留细节

### 风险 2：迁移 print 到 logger 时误改业务逻辑

缓解：

- 本次只改日志语句，不顺手调整控制流
- 先补日志配置测试，再做模块迁移

### 风险 3：配置入口分散，导致实际级别不符合预期

缓解：

- 统一通过 `logging_utils.py` 解析配置和环境变量
- 用测试锁定优先级规则

## Success Criteria

本次优化完成后，应满足：

- 默认运行模式下，单次打印主链路日志明显减少
- 调试模式下，仍能看到预览下载、SSE、轮询、文件清理等细节
- 主要后端模块不再使用手写 `[DEBUG]` / `[INFO]` 的 `print(...)`
- 日志级别可通过配置文件和环境变量控制，且环境变量优先
- 不影响现有功能和测试结果
