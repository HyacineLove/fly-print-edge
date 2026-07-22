# Edge 开发、构建与验证

## 原则

- 协议/状态机须有离线单元测试。
- 真机验收：网线直连目标机上的 HP Color LaserJet Pro 3288dn；开发机发现结果不能替代。
- Python 3.12.10 venv。
- **交付收口：** 本轮 Edge 有改动时，全部改完后再 bump 并打安装包（勿中途反复打包）。Cloud 改动用 compose update，不打 Edge 包。

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

## Cloud 传输地址

- `cloud.base_url` 支持 **http** 与 **https**（受信证书；勿用 `https://localhost` 再改写局域网 IP）。
- WebSocket 由 `url_scheme.http_url_to_websocket_url` 映射为 **ws** / **wss**；REST 与文件下载跟随同一 `base_url`。
