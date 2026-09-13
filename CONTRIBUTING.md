# Contributing to KernelLens

欢迎提交问题、文档改进和代码贡献。首次改动前请阅读 [终端界面](docs/tui.md)、[CLI 手册](docs/cli.md)、[Agent 原理](docs/agent-guide.md) 和 [当前状态](docs/status.md)。

## 环境与检查

需要 Python 3.12 和 uv。在仓库根目录执行：

```bash
uv sync --locked
uv run --locked ruff check src scripts
uv run --locked ruff format --check src scripts
uv run --locked python -m kernellens.knowledge validate
uv run --locked python scripts/sync_diagrams.py --check
```

这些命令使用仓库内的源码、知识包和图源，不需要 API Key 或 GPU。首次安装需要下载锁定的依赖。普通运行所需依赖与 Ruff 开发依赖分组声明；只安装运行环境可使用 `uv sync --locked --no-dev`。

当前仓库按产品使用范围分发，完整自动测试、检索评估问题和真实验收脚本由维护者保存在本地。仓库中的验证数量是维护者记录，不代表克隆后可以直接运行同一测试集，也不表示 GitHub Actions 已执行。

实际使用 Agent 时，将 `.env.example` 复制为 `.env`，填写自己的配置。真实任务及 `--check-api` 会调用供应商，可能计费。

## 提交改动

1. 从 `main` 创建功能分支，一次 PR 解决一个明确问题。
2. 修改相关实现和使用说明，附上最小复现输入、预期行为和实际结果。
3. 运行上面的源码与知识包检查；涉及打包时运行 `uv build` 并核对安装包内容。
4. PR 说明验证命令及未验证的范围；维护者在本地运行完整回归后合并。

提交前用 `git diff --cached --stat`、`git diff --cached` 核对实际上传内容。`.gitignore` 不会清除已提交的历史内容。新增需要公开的使用文档时，同时更新文档白名单和导航。

## 知识包与图源

普通用户不需要 TileLang 克隆。维护者更新知识时按 [RAG 说明](docs/tilelang-rag.md) 重新构建并导出，保留 SQLite、manifest、README、LICENSE 和 THIRDPARTYNOTICES。不要提交本地 TileLang 仓库、重复 JSONL 导出或个人会话数据库。

知识更新应检查完整性与查询质量。检索改善、AST 通过和 GPU 正确性是不同结论；性能改进必须有一致环境下的真实测量。

五张总览图的独立 Markdown 文件是唯一图源，修改后运行 `uv run --locked python scripts/sync_diagrams.py`，再检查生成的展示页。

## 隐私

不要提交 `.env`、凭证、个人路径、对话记录、供应商原始响应或未经检查的生成产物。提交 issue 前对日志脱敏，仅保留能复现问题的最小材料；敏感问题见 [SECURITY.md](SECURITY.md)。
