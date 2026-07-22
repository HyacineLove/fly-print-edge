# FlyPrint Edge — Agent

按需加载（勿整仓通读）：

| 任务 | 文档 |
|------|------|
| **开发计划 / 任务清单** | 工作区根目录 `FlyPrint开发计划.md`、`FlyPrint任务清单.md`（先读） |
| **全量归档（防上下文丢失）** | 工作区根目录 `FlyPrint总开发计划.md` |
| 协议 / 打印链路 / 部署边界 | `docs/agent/architecture-and-protocols.md` |
| 构建 / 测试 / 安装包 | `docs/agent/development-and-verification.md` |
| 发版 P0/P1 待办（M0） | `docs/agent/release-plan.md`（与 Cloud 同名文件保持同步） |
| IPP 人工运维（非 Agent 主入口） | `docs/ipp-printing-architecture.md`、`docs/ipp-printing-operations.md` |

## 硬规则

- 改前先确认数据流、状态流转与 IO 边界；按完整调用链定位后再改。
- 禁止未确认的兜底、替代打印链路或协议分支；改方案先对话确认。
- 可先写小 demo 验证；合入后不得保留重复协议实现。
- 保持模块职责清晰，避免继续堆 `main.py`、Cloud 适配层或单一模块。
- 保留工作区已有改动；提交前检查 `git status --short`，并同步更新受影响说明。
- **完成态**：`[x]` 仅表示已合入（及该项验收所要求的打包/预演）；「代码/单测通过」最多 `[~]`。细则见根目录 `FlyPrint任务清单.md`「用法」第 4 条；勾选须与 `docs/agent/release-plan.md` 同步。
