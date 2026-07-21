# FlyPrint Edge Agent 操作规范

本文件只保留执行任务时必须遵守的通用规范。项目架构、协议、构建和验证说明见：

- [架构与协议说明](docs/agent/architecture-and-protocols.md)
- [开发、构建与验证](docs/agent/development-and-verification.md)
- [发版开发计划 P0/P1](docs/agent/release-plan.md)（plan-execute 权威待办；与 Cloud 同名文件保持同步）

## 必须遵守

- 修改前先确认相关模块的数据流、状态流转以及输入输出边界；按完整调用链定位问题后再改动。
- 不得擅自增加未获确认的兜底、替代打印链路或协议分支；需要改变既定方案时先在对话中提出建议并等待确认。
- 可以先创建小 demo 或离线测试验证可行性，确认后再合并到生产代码；合并后不得保留重复的协议实现。
- 保持模块职责清晰，避免把无关逻辑继续堆入 `main.py`、Cloud 适配层或单一模块。
- 保留工作区已有改动；提交前检查 `git status --short` 和 `git diff -- AGENTS.md`，并同步更新受影响的项目说明。

## 2026-07-21 本轮验证记录

- 集成预览绑定后只上报一次终端会话状态；Cloud 任务绑定不依赖未定义的投递结果变量。
- Edge 全量测试 193 项通过。
- Edge 1.0.37 安装包已构建；Inno Setup 编译器路径为 `C:\Users\HQIT-LAPTOP\AppData\Local\Programs\Inno Setup 6\ISCC.exe`。
- 本轮变更已纳入 Git 提交；发版待办见 `docs/agent/release-plan.md`。
- `runtime/` 已加入 `.gitignore`，本地 SQLite 投递库不入库。
