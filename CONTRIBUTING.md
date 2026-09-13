# Contributing to KernelLens

欢迎提交问题、文档改进和代码贡献。首次改动前请阅读 [CLI 手册](docs/cli.md)、[Agent 原理](docs/agent-guide.md) 和 [当前状态](docs/status.md)。早期学习讲义用于解释设计过程，不是当前开发的执行限制。

## 开发环境

需要 Python 3.12 和 uv。在仓库根目录执行：

```bash
uv sync --locked
uv run --locked python scripts/check_project.py
```

检查包含 Ruff、pytest、知识包校验、28 条检索回归、文档本地链接和五图同步。全部使用离线数据或 localhost 替身，不需要 API Key 或 GPU。首次同步需要从依赖源下载锁定版本。

实际运行 Agent 时，将 `.env.example` 复制为 `.env`，填写自己的模型配置。`scripts/smoke_live.py`、`scripts/smoke_rag_live.py --run-live` 和 CLI `--check-api` 会调用真实供应商，可能计费，不属于默认开发检查。

## 提交改动

1. 从 `main` 创建功能分支，一次 PR 解决一个明确问题。
2. 修改相关实现和使用说明。行为改变时添加能复现问题的测试。
3. 运行本地检查；涉及打包时运行 `uv build` 并检查内置知识文件。
4. PR 描述包含问题、最终行为、验证命令和仍未验证的范围。

提交前用 `git diff --cached --stat`、`git diff --cached` 核对实际上传内容。`.gitignore` 只影响未跟踪文件，已经进入历史的密钥不能靠添加忽略规则清除。

## 知识包

普通用户不需要 TileLang 克隆。维护者更新知识时按 [RAG 说明](docs/tilelang-rag.md) 重新构建并导出，提交内置目录中的 SQLite、manifest、README、LICENSE 和 THIRDPARTYNOTICES。不要提交本地 TileLang 仓库、重复 JSONL 导出或个人会话数据库。

知识更新应保留来源和许可信息，检查完整性并运行查询回归。检索改善、AST 通过和 GPU 正确性是不同结论；性能改进必须有一致环境下的真实测量。

## 文档与隐私

五张总览图的独立 Markdown 文件是唯一图源，修改后运行 `uv run --locked python scripts/sync_diagrams.py`，再检查生成的展示页。

不要提交 `.env`、凭证、个人路径、对话记录、供应商原始响应或未经检查的生成产物。提交 issue 前对日志脱敏，仅保留能复现问题的最小材料；敏感问题见 [SECURITY.md](SECURITY.md)。
