# FlyPrint Edge 直接 IPP 打印架构

## 数据流

```text
上传文件
  -> DocumentPipeline（哈希校验、标准 PDF、预览与排版）
  -> IppPrintService（设备串行锁与状态机）
  -> IppClient.Print-Job（直接提交 application/pdf）
  -> 设备 Job ID
  -> Get-Job-Attributes / Get-Printer-Attributes
  -> completed / failed / canceled / unconfirmed
```

Windows 不需要安装打印队列、驱动或 SumatraPDF。生产代码不包含 Windows Spooler、WSD、WMI、RAW Socket 或其他提交回退。

## 模块边界

| 模块 | 输入 | 输出 | 职责 |
|---|---|---|---|
| `domain.py` | 原始打印参数 | 强类型请求、状态和错误 | 领域模型与中文用户提示 |
| `documents.py` | 文件身份和延迟源供应器 | 标准 PDF、预览页、打印专用 PDF | 哈希校验、类型归一化、缓存、预览和一致排版 |
| `ipp_protocol.py` | IPP URI、属性、PDF 流 | 严格解析的 IPP 响应 | IPP/2.0 编解码、分块发送、超时和响应校验 |
| `ipp_device.py` | IPP 属性 | 能力、快照和故障 | 能力归一化、参数验证、故障归因 |
| `discovery.py` | DNS-SD 服务记录 | IPP 候选设备 | 解析 `rp`、并行探测、UUID 去重 |
| `service.py` | `PrintRequest` | `PrintEvent` 流和终态 | 串行锁、准备、提交、监控、取消和清理 |

HTTP、管理端、用户端和 Cloud 代码都是适配层，不实现协议或打印状态判定。

PDF、Office 和图片都先生成由 `content_hash + 文件类别 + 转换版本` 标识的标准 PDF。预览和打印共用该 PDF；打印参数只产生任务专用 PDF，任务终止后立即删除。标准 PDF 使用30分钟滑动 TTL、活跃租约和5分钟清理周期，原始下载文件只在标准 PDF 验证成功后删除。

Office 转换使用 Edge 专属固定 LibreOffice Profile，并由进程内唯一互斥锁串行执行。全新 Profile 在 Edge 启动后异步转换内置小型 DOCX 完成预热；成功标记同时绑定 LibreOffice 可执行文件指纹。Profile 已初始化时跳过预热，不启动常驻进程，也不使用其他转换路径。

## 状态机

```text
PREPARING -> SUBMITTING -> QUEUED -> PRINTING -> COMPLETED
                           |          |          
                           +----------+-> FAILED / CANCELED / UNCONFIRMED
```

- `pending`、`pending-held` 映射为 `QUEUED`。
- `processing` 映射为 `PRINTING`。
- 只有 `completed` 映射为 `COMPLETED`。
- `aborted` 映射为 `FAILED`；`canceled` 映射为 `CANCELED`。
- 提交响应丢失、作业查询失败或取消无法确认均映射为 `UNCONFIRMED`。
- Edge 本地事件直接保留 `job-impressions-completed` 对应的页数进度。用户端按页显示“正在打印，第 N / M 页”，不将双面页数换算为物理纸张。
- Cloud 状态消息只保留任务状态，不发送或持久化逐页进度。
- 用户端刷新后从交互会话快照恢复当前阶段和页数进度；`UNCONFIRMED` 在管理员解除设备锁前禁止返回二维码页。

## 协议约束

- URI 必须是包含主机、端口和资源路径的完整 `ipp://` URI。
- Print-Job 始终发送 `application/pdf`、明确 `Content-Length` 和 `ipp-attribute-fidelity=true`。
- PDF 以固定块读取并发送，不复制整份文件到第二个内存缓冲区。
- 响应必须通过 HTTP、IPP 状态、request-id、长度和属性类型校验。
- 份数、单双面、色彩和 PWG media 在提交前验证；设备不支持时明确失败。

## 并发、故障和清理

- 以 `printer-uuid` 建立进程内互斥；正式、Cloud 和测试任务共用。
- 设备警告或 report 只记录，不单独取消当前任务。
- 当前 Job 明确故障或设备 `*-error` 才归因并取消。
- Job 已 completed 时完成优先；随后出现的缺纸只阻止下一任务。
- 15 分钟超时后 Cancel-Job；取消结果不明确则保持 `UNCONFIRMED` 锁。
- 按部署约定不持久化活动 Job，Edge 重启后不恢复旧作业。

## 配置与标识

`printer_schema_version=2` 首次迁移时清除旧 Windows/WSD/USB 记录。`id` 是 Edge 本地稳定标识；`cloud_id` 单独保存，Cloud 回包不得覆盖本地 ID。同一 `printer-uuid` 地址变化时，重新探测通过后更新 URI。
