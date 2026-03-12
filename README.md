# FlyPrint Edge

边缘打印服务：对接 FlyPrint Cloud，管理本机打印机，提供扫码上传→预览→打印 Kiosk 及管理端。

---

## 启动（3 步）

1. **配置**  
   ```bash
   cp config.example.json config.json
   ```  
   编辑 `config.json`：`cloud.base_url`、`cloud.auth_url`、`cloud.client_secret`（与 Cloud 一致）；局域网访问将 `network.bind_address` 设为 `0.0.0.0`。

2. **依赖**  
   ```bash
   python -m venv venv
   # Windows: .\venv\Scripts\Activate.ps1
   # Linux/macOS: source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **运行**  
   ```bash
   python main.py
   ```  
   或使用脚本：Windows `.\start.ps1`，Linux/macOS `./start.sh`（可选 `-Setup` 自动建 venv 并装依赖）。

访问：**用户端** `http://localhost:7860/`，**管理端** `http://localhost:7860/admin`。

---

## 功能

- **用户端 (Kiosk)**：获取上传二维码 → 扫码打开 Cloud 上传页 → 在本机预览 → 提交打印。
- **管理端**：查看/添加/删除打印机、设默认打印机、查看云端连接状态、节点/打印机重注册。
- **云端同步**：节点与打印机注册、心跳、状态上报、接收下发任务与上传凭证；所有 URL 随 Cloud 挂载点（含子路径）正确拼接。
- **预览缩放**：支持 `scale_mode`（fit/actual/fill），与 Cloud 约定一致。

---

## 结构（精简）

```
fly-print-edge/
├── main.py              # 入口、路由、SSE
├── config.json          # 配置（不提交）；config.example.json 为模板
├── cloud_*.py           # 认证、REST、WebSocket、心跳、状态
├── printer_*.py         # 配置、发现、队列、Windows/Linux 实现
├── file_manager.py      # 预览文件生命周期
├── portable_temp.py     # 可移植临时目录
├── tests/               # 测试与探测脚本（在项目根运行 python tests/xxx.py）
└── static/
    ├── user/            # 用户端页面与逻辑
    └── admin/           # 管理端页面与逻辑
```

---

## 亮点

- **单文件配置**：全部使用 `config.json`，无环境变量依赖；`base_url`/`auth_url` 含子路径即可适配 Cloud 子路径部署。
- **与 Cloud 解耦**：仅依赖 Cloud 的 REST + WebSocket 约定与 OAuth2 客户端，便于独立部署与扩展。
- **预览与打印闭环**：支持 PDF/图片/Word（转 PDF）预览，缩放模式（fit/actual/fill）、纸张检测与打印参数与 Cloud 一致。
- **可移植临时目录**：预览与临时文件落在项目内 `temp/`，便于迁移与清理。
- **测试集中**：脚本统一放在 `tests/`，根目录执行即可。

详见 **[HANDOFF.md](./HANDOFF.md)**。
