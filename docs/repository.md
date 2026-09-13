# 仓库分发内容

当前仓库为私有，项目许可证暂不指定。最新版本按产品使用范围分发 KernelLens 与内置知识包，测试和学习过程文件保留在维护者本地。

| 上传 | 用途 |
| --- | --- |
| `src/` | Agent、TUI、命令联想、内置知识数据库与上游许可 |
| `docs/` 中的使用/原理文档、架构决策和总览图源 | 说明功能、配置、工作原理与当前边界 |
| `scripts/sync_diagrams.py` | 从独立图源生成五图展示页 |
| `examples/verification-report.example.json` | 用户回传真实服务器验证结果的格式模板 |
| README、CONTRIBUTING、SECURITY、NOTICE | 使用、贡献、安全和第三方说明 |
| `pyproject.toml`、`uv.lock`、`.python-version` | 安装入口、运行/开发依赖与版本锁定 |
| `.env.example`、`.gitignore`、`.gitattributes`、`.github/` | 配置模板、文件规则和 issue/PR 模板 |

| 留在本地 | 原因 |
| --- | --- |
| `tests/`、`pytest.ini` | 完整开发回归；不是运行 Agent 必需内容 |
| `knowledge/evaluation_queries.json` | 维护者的检索评估数据；区别于 `src/` 中必需的知识包 |
| 测试、评估及真实验收脚本 | 维护者检查工具，不是产品启动入口 |
| 逐步学习讲义和对应细节图 | 保留开发过程，当前使用与原理由主文档说明 |
| `.env`、凭证、私钥 | 每个使用者提供自己的配置 |
| `.kernellens/`、`artifacts/` | 会话、日志、临时实验及未验收候选 |
| `tilelang/` | 独立上游克隆；用户只需要内置知识包 |
| `.venv/`、缓存、`dist/`、`build/` | 可以重新安装或生成 |
| AGENTS、PROJECT_STATE、一次性计划 | 个人协作与工作状态 |
| 系统/编辑器临时文件 | 与运行无关 |

内置 `src/kernellens/data/tilelang/index.sqlite3` 是产品数据，必须上传；不能当作缓存删除。SQLite sidecar 临时文件不上传。第三方许可与正文一同保留。

此前上传过的测试和讲义从最新版本移除，本机文件仍保留。旧提交仍可查看这些内容；本次采用正常追加提交，不重写远端历史。更早的个人学习历史分支仍只保留在本地，不推送。

用户可按 [贡献指南](../CONTRIBUTING.md) 执行源码、知识包、图源和构建检查；[验证说明](validation.md) 另外记录维护者本地测试。当前没有发布 PyPI 包、GitHub Release 或运行 GitHub Actions。
