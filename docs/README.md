# 文档导航

## 使用和维护当前版本

- [CLI 手册](cli.md)：安装、模型配置、GPU 输入和会话恢复。
- [Agent 功能与方法原理](agent-guide.md)：从用户输入到工具执行、检索、审核和报告。
- [TileLang RAG](tilelang-rag.md)：知识来源、索引、检索和知识包更新。
- [当前能力](status.md)、[工程验证](validation.md)和[RAG 验证](rag-validation.md)：已验证结果与边界。
- [仓库分发内容](repository.md)：需要提交的文件和应留在本地的内容。
- [CLI 架构决策](decisions/002-cli-agent.md)、[RAG 决策](decisions/003-tilelang-rag.md)和[知识包分发决策](decisions/004-bundled-knowledge.md)。

## 学习与设计历史

本目录保留从 Task、State、Action、工具契约到 Agent Loop 的逐单元讲义，以及 [五图展示页](diagrams/README.md) 和各专题图源。这些材料中的“待实现”、阶段测试数和旧提交号反映当时的学习过程，不是当前产品状态，也不是对所有贡献者的开发限制。

开始使用请优先阅读 CLI 手册；研究当前实现请阅读 Agent 原理和源码；参与贡献请遵循 [CONTRIBUTING.md](../CONTRIBUTING.md)。
