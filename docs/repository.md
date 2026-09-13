# 仓库分发内容

当前仓库为私有，项目许可证暂不指定。上传的是可安装、可检查的 KernelLens 与知识包；后续开放仓库前再确定自有代码的许可。

| 上传 | 用途 |
| --- | --- |
| `src/` | Agent 实现以及内置知识数据库、manifest、来源和上游许可 |
| `tests/`、`knowledge/` | 自动测试、检索回归问题 |
| `scripts/`、`examples/` | 开发检查、维护命令、显式真实验收和报告模板 |
| `docs/`、README、CONTRIBUTING、SECURITY、NOTICE | 使用、设计、验证、协作与第三方说明 |
| `pyproject.toml`、`uv.lock`、`.python-version` | 安装入口、依赖声明及可复现版本 |
| `.env.example`、`.gitignore`、`.gitattributes`、`.github/` | 配置模板、忽略/文件规则和 issue/PR 模板 |

| 留在本地 | 原因 |
| --- | --- |
| `.env`、凭证、私钥 | 每个使用者提供自己的配置，不能随仓库分发 |
| `.kernellens/`、`artifacts/` | 会话、模型响应、日志、临时实验和未验收候选 |
| `tilelang/` | 维护者的独立上游克隆；普通用户只需要内置知识包 |
| `.venv/`、各类缓存、`dist/`、`build/` | 可由锁文件和构建命令重新生成 |
| AGENTS、PROJECT_STATE、一次性实施计划 | 个人协作指令和工作状态；公开入口使用本目录的状态及设计文档 |
| 系统/编辑器临时文件 | 与运行和维护无关 |

内置 `index.sqlite3` 是产品运行数据，必须上传；不能因为它是数据库或二进制文件就当缓存忽略。临时 SQLite sidecar 文件不上传。

GitHub 初始提交采用经过整理的快照，旧学习提交保留在本地历史分支，不推送。忽略规则不会清除旧提交内容，因此不能直接把含个人工作状态的旧历史一起推到新仓库。

自动化检查以 `uv run --locked python scripts/check_project.py` 为入口。当前上传不预设 GitHub Actions 已运行，也不发布 PyPI 包或 GitHub Release。
