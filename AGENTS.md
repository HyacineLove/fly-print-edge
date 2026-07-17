# FlyPrint Edge 开发约定

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

## 实施原则

- 只接受完整 `ipp://` URI；不猜测资源路径，不绕过证书，不支持 IPPS。
- 设备 `job-state=completed` 是成功的唯一完成条件。
- 网络或协议状态不明确时返回 `UNCONFIRMED`，不能推断成功。
- 同一 `printer-uuid` 同时只允许一个 FlyPrint 作业。
- 文档转换、预览和打印使用同一排版模型。
- 可先建立小 Demo 验证协议行为；合入生产后不得保留重复协议实现。
- 文件修改使用小而清晰的模块，避免继续扩大 `main.py` 和 Cloud 适配层。

## 验证

- 开发与构建使用 Python 3.12.10 venv。
- 协议与状态机必须有离线单元测试。
- 真实设备行为必须在网线直连 HP Color LaserJet Pro 3288dn 的目标机器验收。
- 不得用当前开发机的发现结果替代目标机器验收。
