# Edge 开发、构建与验证

## 原则

- 协议/状态机须有离线单元测试。
- 真机验收：网线直连目标机上的 HP Color LaserJet Pro 3288dn；开发机发现结果不能替代。
- Python 3.12.10 venv。

## 常用命令

```powershell
# 测试（在 fly-print-edge 根目录，激活开发 venv 后）
python -m pytest

# 安装包：先 PyInstaller，再 Inno Setup
# PyInstaller: .venv-build-3.12.10\Scripts\pyinstaller.exe
# ISCC: C:\Users\HQIT-LAPTOP\AppData\Local\Programs\Inno Setup 6\ISCC.exe
pyinstaller --noconfirm flyprint-edge.spec
& "C:\Users\HQIT-LAPTOP\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
# 输出: dist\flyprint-edge-setup-<版本>.exe ；版本见 installer.iss → MyAppVersion
```

- `runtime/` 已 gitignore（本地 SQLite 投递库不入库）。
