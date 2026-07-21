# FlyPrint Edge 开发、构建与验证

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

## Windows 安装包构建

- PyInstaller 构建环境：`D:\HQIT-LAPTOP\FlyPrint\fly-print-edge\.venv-build-3.12.10\Scripts\pyinstaller.exe`。
- Inno Setup 6.7.3（当前用户安装）的编译器：`C:\Users\HQIT-LAPTOP\AppData\Local\Programs\Inno Setup 6\ISCC.exe`。
- 构建顺序：先在仓库根目录执行 `pyinstaller --noconfirm flyprint-edge.spec`，再执行 `ISCC.exe installer.iss`。
- 安装包输出到 `dist\flyprint-edge-setup-<版本>.exe`；版本号由 `installer.iss` 的 `MyAppVersion` 定义。
- 2026-07-21 已用上述 Inno Setup 6.7.3 路径成功编译 Edge 1.0.37 安装包；后续构建直接复用该路径。
