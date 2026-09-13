# 技术方向与 Apple Silicon 兼容性

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

初始调研基准：2026-09-08；TOOL-001A 的 Pydantic 选型与本机验证更新于 2026-09-10。下列方案区分“已采用的方向”和“待安装验证”，具体引入前核对官方文档并锁定实际版本。

## 组件决策表

| 项目与时机 | 解决什么问题／为何此时需要 | 不使用会怎样／更简单方案 | 当前选择及原因 |
| --- | --- | --- | --- |
| Python，FND-003 | 统一运行环境与包兼容性 | 复用系统 Python 易与其他项目耦合 | 已验证原生 ARM64 CPython 3.12.13；GPU Runner 独立选版本，第三方依赖兼容性随引入验证 |
| 包管理，FND-003 | 解释器、依赖和复现 | venv + pip 可用但步骤分散 | 已验证 uv 0.11.23 + 项目 .venv + uv.lock；不混用 Conda 与项目依赖 |
| 构建，FND-004A | 将 src 源码安装为可导入包 | 手工修改导入路径会掩盖安装问题；Hatchling/setuptools 也可用 | 固定 uv_build 0.11.23；当前纯 Python，复用原生 uv 内置后端；可编辑与普通 wheel 安装均已验证 |
| Config，FND-004B | 将外部字符串变为可靠配置、让测试控制输入 | 散落读取环境难验证；单字段不必引入设置框架 | 已实现标准库 dataclass + 显式环境映射，通过配置行为测试；业务预算属于后续核心逻辑 |
| Schema，RUN/TOOL | 工具输入需要同时校验数据与导出参数规则 | 单字段可手写；维护校验和 Schema 两份规则易失配 | TOOL-001A 已安装锁定 Pydantic 2.13.5 并验证 ARM64；从 ReadReportArguments 开始，模型待用户实现；既有领域 dataclass 保留，见 ADR 001 |
| Runtime，RUN | 理解并控制 loop、state 和终止 | SDK 可代管，但隐藏部分学习环节 | 自研有限 Runtime；不建设通用 Agent 框架 |
| 模型，MOD | 真实工具决策与代码生成 | FakeModel 只能测程序控制流 | 先一个云端 API，接入前确定模型、预算和数据范围 |
| Tool Calling，TOOL/MOD | 把模型提议变成可校验动作 | 解析自由文本不可靠 | 明确 Schema、call ID、Observation 和本地权限检查 |
| Workflow，RUN | 确定性关卡与状态转移 | 自由循环难以约束 | 普通 Python 状态逻辑；需求复杂后再评估框架 |
| RAG，EVD | 用当前源码支持实现与优化 | 全量塞入上下文成本高；仅靠模型记忆不可靠 | 先精确符号、关键词、元数据；按案例补中英文术语 |
| Vector DB，待定 | 大规模语义检索 | 当前小语料可用普通索引 | 暂不引入；召回质量与规模证明需求后再选 |
| Database，STO | 保存 run、步骤及产物关联 | JSON 文件简单但事务和查询更弱 | SQLite 单写入者；是否 ORM 后续按需求判断 |
| API，SVC | 外部提交、查询与取消任务 | CLI 已足够完成 MVP | V1 引入 FastAPI，复用应用层 |
| Async，MOD/TOOL | 超时、取消与 I/O 等待 | 简单同步可起步 | 用 asyncio 学习有界异步；只并发无依赖的只读操作 |
| Queue，待定 | 多任务后台执行及恢复 | 单任务 CLI 无此需求 | 暂不引入；进程内后台任务不承诺持久性 |
| Cache，待定 | 避免重复请求或重复解析 | 先测量也能完成系统 | 先记录重复率；缓存需按内容和版本失效 |
| Logging，RUN 起 | 排查每一步发生了什么 | print 难关联任务 | 结构化 run/step 记录，必要脱敏 |
| Tracing，OBS | 查看完整调用轨迹与耗时 | 本地步骤记录可支撑 MVP | V1 查询轨迹；确有导出需求再用 OpenTelemetry |
| Evaluation，EVAL | 测量质量和变更效果 | 主观判断无法回归 | 自有案例、评分规则、基线报告；不先部署评测平台 |
| Testing，FND 起 | 验证确定性逻辑与集成边界 | 普通 assert 脚本可起步，自动收集和失败报告需自行维护 | pytest 9.1.1 开发依赖；已验证配置、领域契约与替身 Runtime；依赖变更后原有 326 个测试通过 |
| Lint/Format，FND-004B | 统一常见代码检查、导入与排版 | 手工检查可用但重复；也可组合独立检查和格式化工具 | Ruff 0.16.6 开发依赖，已验证 Mach-O arm64；当前作用于 src/tests，不代替行为测试 |
| Docker，DEP | 验证交付环境与持久化 | 前期原生运行更易调试 | V1 使用 Linux ARM64 镜像；选择 tag 时检查架构并固定版本 |
| CI/CD，DEP | 干净环境回归与可重复发布 | 先本地检查即可 | 先 GitHub Actions CI，再构建发布；不自动公开部署 |
| Deployment，DEP | 形成独立可运行服务 | CLI 本地运行支撑 MVP | 单实例与持久卷；公开访问前加入鉴权及资源限制 |

## Agent 框架比较

下面的学习与工程判断针对本项目，不是框架通用排名。

| 方案 | 学习价值与黑盒程度 | 灵活性与维护成本 | 本项目结论 |
| --- | --- | --- | --- |
| 自研有限 Runtime | loop、state、tool result 和恢复可直接学习；黑盒少 | 领域约束灵活，控制流与可靠性自行维护 | 作为教学主线与可测基线；不复刻厂商 HTTP 客户端 |
| OpenAI Agents SDK | 提供 loop、sessions、tracing、guardrails；部分执行细节代管 | 适合标准编排，需理解 SDK 的状态与错误语义 | 完成原理学习后可做替换实验 |
| LangGraph | 图、状态、checkpoint、人工介入更显式 | 适合复杂恢复与分支，增加图执行模型的维护 | 当恢复复杂度确实升高时优先评估 |
| LangChain | 集成与预构建 Agent 方便，抽象层较多 | 减少适配工作，需追踪组合依赖 | 初期不作为入口，具体集成有需求时使用 |
| AutoGen | 强调 Agent 通信与协作 | 官方仓库已进入维护模式 | 不作为当前新项目基础 |
| CrewAI | Crews 与 Flows 分别组织协作和流程 | 角色抽象适合团队式任务，也会增加概念 | 当前单 Agent 不需要引入 |

简历价值来自可解释的边界、恢复语义、评测与真实结果。框架名称本身不是技术成果。框架迁移必须与原实现使用同一案例和明确资源条件比较，保留能被数据支持的方案。

官方依据：[OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)、[Function Calling](https://developers.openai.com/api/docs/guides/function-calling)、[LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)、[LangChain](https://docs.langchain.com/oss/python/langchain/overview)、[AutoGen](https://github.com/microsoft/autogen)、[CrewAI](https://docs.crewai.com/en/introduction)。

## Mac M4 检查策略

- FND-003 已验证 arm64、/opt/homebrew/bin/uv 0.11.23 和独立 .venv；复用 uv 已管理的 CPython 3.12.13。步骤与证据见 [environment.md](environment.md)。
- Homebrew 默认 python3 为 3.14.6；项目通过 .python-version 和 uv run 选择 3.12.13。共享解释器不等于共享项目依赖。
- TOOL-001A 已添加 Pydantic 2.13.5 运行依赖；项目本身保持可编辑安装。环境与原生扩展检查仅在本机进行，不扩大为服务器兼容性证明。
- 不把 Rosetta 作为默认修复。若缺少匹配 wheel，先判断是否可替换依赖，再决定是否需要本地编译。
- Python 原生扩展可能仍需编译；“支持 ARM64”不代表任何版本组合都能直接安装。
- uv 将 Apple Silicon macOS 列为 Tier 1；仍需在本项目锁定依赖并实际验证。[uv 平台支持](https://docs.astral.sh/uv/reference/policies/platforms/)
- Docker Desktop 有 Apple Silicon 版本，Rosetta 并非严格必需；优先运行 linux/arm64 镜像。[Docker Mac 安装](https://docs.docker.com/desktop/setup/install/mac-install/)
- Python 官方 3.12-slim 系列包含 arm64v8；部署时检查实际 tag 与 manifest，不仅凭镜像名称判断。[官方 Python 镜像](https://github.com/docker-library/official-images/blob/master/library/python)
- Mac 上的普通 Linux 容器不能作为 CUDA 验证环境；相关 NVIDIA GPU 支持文档面向 Windows WSL2。目标 GPU 测试放在对应服务器。[Docker GPU 文档](https://docs.docker.com/desktop/features/gpu/)

## TOOL-001A 依赖验证

2026-09-10 采用正式版 Pydantic 2.13.5；取舍见 [ADR 001](decisions/001-tool-input-schemas.md)。
它支持从模型生成 JSON Schema，本项目用来保持工具参数声明与导出规则一致。[官方文档](https://docs.pydantic.dev/latest/concepts/json_schema/)

助手实际执行：

```bash
uv add --no-cache --no-python-downloads --no-build-package pydantic-core 'pydantic==2.13.5'
```

- uv.lock 新增 pydantic 2.13.5、pydantic-core 2.46.5、annotated-types 0.8.0、typing-extensions 4.16.0、typing-inspection 0.4.4；原有包版本未改变。
- 本机 CPython 3.12.13 / arm64；pydantic-core 的安装标签为 cp312-cp312-macosx_11_0_arm64，扩展文件为 Mach-O arm64。
- 安装禁止本地构建 pydantic-core，使用已构建 wheel；没有调用 Rosetta、Cargo 或系统 Python。其发行提供匹配的 ARM64 文件。[发行文件](https://pypi.org/project/pydantic_core/2.46.5/)
- 依赖安装后实际回归 326 passed（0.12s），Ruff lint/format 通过（33 个 Python 文件）；工具参数模型与新测试尚未实现。
- 日常复现使用 `uv sync --locked`；当前工具参数类不读取文件，也未接入真实模型或服务器。

## 本地模型与远程执行

当前选择云端 API，但供应商、模型、预算未定；开发前段使用 FakeModel。若以后需要本地模型，优先测试 macOS 原生 Ollama 或 MLX，并结合实际内存和工具调用质量选择模型。

[Ollama](https://docs.ollama.com/macos) 支持 Apple M 系列 CPU/GPU；[MLX](https://ml-explore.github.io/mlx/build/html/install.html) 文档强调原生 ARM Python。它们是候选，不是本项目已安装依赖。

Agent 控制服务、云端模型和 GPU 执行器拥有不同职责及环境。后续自动执行仍需要单独设计权限和隔离，不能通过混装 CUDA 依赖解决。
