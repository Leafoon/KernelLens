# Engineering Backlog

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

结构为 Epic → Feature → Task。下表是计划，最新完成状态以 [当前能力与验证范围](status.md) 和 Git 为准。
标注的 Files 是未来目标路径，不表示文件已创建。每个 Task 可以拆成多个学习单元；每轮最多一个单元。

优先级：P0 为对应版本必须完成，P1 为版本完整性增强，P2 为按实际需求实施的扩展。
依赖 ID 是先决条件，不能因为文件创建方便就跳过；确需调整依赖时先说明原因并更新本表。

## Epic FND：项目基础 → 独立仓库、设计与环境

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| FND-001 独立项目身份 | 初始化内层仓库和上下文文件 | P0 | 设计确认 | README.md、AGENTS.md、docs/status.md、.gitignore | 独立 Git Root；四文件检查通过；用户完成首提交 | repository、暂存与提交、文件恢复上下文 |
| FND-002 设计归档 | 保存产品、架构、技术、路线、任务、学习和质量文档及五图 | P0 | FND-001 | docs/*.md、docs/diagrams/*、scripts/sync_diagrams.py、README.md、docs/status.md | 三项主要功能范围一致；五图有独立源且展示同步；相对链接有效；没有核心实现 | 需求、架构、Backlog 与图源的职责 |
| FND-003 原生环境 | 选择并验证 ARM64 Python 与 uv 项目环境 | P0 | FND-002 验收 | .python-version、pyproject.toml、uv.lock、docs/environment.md、.gitignore（如需） | 解释器与虚拟环境路径可确认；原生架构；当前声明在干净环境可复现 | 解释器、虚拟环境、依赖锁定 |
| FND-004 基础配置与检查入口 | 分单元建立可安装包、集中环境配置和 lint/pytest 基础 | P0 | FND-003 | src/kernellens/__init__.py、src/kernellens/config.py、tests/test_config.py、pyproject.toml、uv.lock | 包可安装导入；配置加载与非法值行为可验证；无付费模型调用；基础检查可运行 | 模块、构建、配置、异常与 pytest |

## Epic RUN：执行核心 → 任务契约与有限循环

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| RUN-001 Task 与 State | 明确三类任务输入、生命周期与验证状态的区别，组合最小 TaskState | P0 | FND-004 | src/kernellens/domain/task.py、state.py、verification.py；tests/test_task.py、test_state.py、test_verification.py、test_task_state.py | 请求类型合法且目标非空；未执行不能是通过；非法状态转换有明确行为；状态更新保留请求与检查结果；模型与运行状态分离 | Domain Model、组合与不变量 |
| RUN-002 Action 与 Observation | 表达工具提议、请求信息、结果与错误，校验外部输入边界与参数快照 | P0 | RUN-001 | src/kernellens/domain/action.py、src/kernellens/domain/observation.py；tests/test_action.py、tests/test_tool_call_action.py、tests/test_finish_action.py、tests/test_action_parser.py、tests/test_observation.py | 非法结构失败；行动提议不直接改状态；工具参数不随原输入漂移；结果提交不代替业务验收；调用成功与检查失败可同时表示，无报告与未运行可区分 | Structured Output、边界转换、数据所有权与结果语义 |
| RUN-003 最小 Runtime | 先完成单次决策、预算与行动处理，再用模型和工具替身实现有界循环 | P0 | RUN-002 | src/kernellens/runtime/step.py、budget.py、handlers.py、records.py、loop.py；tests/test_runtime_step.py、test_decision_budget.py、test_request_input_handler.py、test_finish_handler.py、test_tool_call_handler.py、test_step_record.py、test_run_result.py、test_loop.py；替身有复用需要时再抽取 | 决策前校验；失败尝试消耗额度；行动改变状态；审核接受才完成；反馈可传入；结束、等待、非法行动与预算耗尽均可测；每步有记录 | Dependency Injection、预算、Action Handler、完成审核、Agent Loop、状态转移、终止 |

## Epic TOOL / MOD：外部能力 → 工具与模型接入

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| TOOL-001 Tool Registry | 先建立工具参数与 Schema，再定义工具身份、注册及调用入口 | P0 | RUN-002 | src/kernellens/tools/arguments.py、后续 registry.py；tests/test_tool_arguments.py、后续 test_registry.py；工具定义文件在对应单元确定 | 参数契约与导出规则一致；重名拒绝；未知工具失败；输入 Schema 明确 | Tool Schema、注册和路由 |
| TOOL-002 受控执行器 | 校验参数、路径、超时与返回值 | P0 | TOOL-001、RUN-003 | src/kernellens/tools/executor.py、tests/unit/test_executor.py | 越界路径失败；超时可观察；业务失败不能标记检查通过 | 执行边界、async、错误分类 |
| MOD-001 单 Provider | 封装一个云端 API 与 usage；保留测试替身 | P0 | RUN-003、模型与预算确认 | src/kernellens/models/base.py、src/kernellens/models/provider.py、tests/unit/test_model_adapter.py | 不在日志输出密钥；结构失败和限流行为可测；记录实际模型 | 模型抽象、重试、资源记账 |
| MOD-002 Tool Calling 集成 | 串联模型提议、真实工具与 Observation | P0 | MOD-001、TOOL-002 | src/kernellens/runtime/loop.py、tests/integration/test_tool_loop.py | call ID 配对；无效提议受限纠正；真实 API 测试单独启用 | 多轮工具调用与上下文协议 |

## Epic EVD / DEV：产品能力 → 证据、生成、优化与诊断

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| EVD-001 证据契约与素材 | 核对知识来源、许可、源码版本和内容标识 | P0 | TOOL-002 | src/kernellens/evidence/models.py、src/kernellens/evidence/ingest.py、tests/unit/test_evidence.py | 关键字段不可缺；失效证据显式失败；不依赖相邻旧仓库 | Provenance 与版本漂移 |
| EVD-002 受控检索 | 精确符号、关键词及元数据检索，按需读取源码片段 | P0 | EVD-001、MOD-002 | src/kernellens/evidence/search.py、src/kernellens/tools/source.py、tests/integration/test_retrieval.py | 必需符号逐项确认；设备冲突不吞掉；中文术语有案例 | RAG、召回与证据核对 |
| DEV-001 按需生成 GEMM | 需求确认、候选代码、静态检查、测试与说明 | P0 | EVD-002 | src/kernellens/workflows/generate.py、src/kernellens/artifacts.py、prompts/generate.md、tests/integration/test_generation.py | 交付覆盖契约；引用有效；候选仅保存到产物目录；未运行状态明确 | 需求到代码与产物版本 |
| DEV-002 优化候选 | 维护 baseline、提出可验证假设并生成优化版本 | P0 | DEV-001 | src/kernellens/workflows/optimize.py、prompts/optimize.md、tests/integration/test_optimization.py | 不改变计算契约；baseline 可追踪；无实测不宣称提速 | 优化假设、对照实验 |
| DEV-003 诊断与报告检查 | 分析日志、排除假设、给出修复或请求信息 | P0 | DEV-001 | src/kernellens/workflows/diagnose.py、src/kernellens/report_verifier.py、tests/integration/test_diagnosis.py | 支持／反驳证据可查；缺口阻止过度结论；共享 Runtime | 调查、Re-planning、验收关卡 |

## Epic CTX / STO：上下文与运行记录 → 任务记忆

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| CTX-001 Context Builder | 按预算挑选证据和观察，保留协议完整性 | P0 | DEV-001、DEV-002、DEV-003 | src/kernellens/context/builder.py、tests/unit/test_context.py | 不超配置限额；关键约束与失败不丢；tool call/result 配对 | Context Engineering 与污染隔离 |
| STO-001 Run 持久化 | 保存状态、步骤和产物引用；暂不承诺自动恢复 | P0 | CTX-001 | src/kernellens/storage/sqlite.py、tests/integration/test_storage.py | 单写入者；重新启动能查询完整记录；失败保存不会伪报完成 | 事务、任务记忆与审计 |

## Epic EVAL：质量体系 → 基线与回归

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| EVAL-001 案例与基线 | 整理人工审核案例，建立单次 LLM 和固定 Workflow | P0 | STO-001；场景定义从 Phase 0 起 | evals/cases/、evals/baselines/、docs/quality.md | 案例有来源与判据；开发／保留集区分；条件可比 | 评测集、基线与数据泄漏 |
| EVAL-002 指标与报告 | 实现核心评分、统计、失败归因和回归 | P0 | EVAL-001 | src/kernellens/evaluation/、evals/reports/、tests/unit/test_metrics.py | 缺失 usage 非零填充；不靠拒答刷分；关键不变量通过 | Evaluator、成本／质量取舍 |

## Epic SVC / REL / OBS：V1 服务 → 操作、恢复与观测

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| SVC-001 任务 API | 复用应用入口，暴露创建与查询接口 | P0（V1） | EVAL-002 | src/kernellens/api/、tests/integration/test_api.py | 限定并发；输入与运行状态一致；不把后台函数当持久队列 | 应用层与接口边界 |
| REL-001 恢复与取消 | 明确 interrupted、恢复点、版本检查与取消传播 | P0（V1） | SVC-001 | src/kernellens/runtime/recovery.py、tests/integration/test_recovery.py | 断点有证据；重试不会误记完成；无法安全重放时停止 | checkpoint、幂等与故障恢复 |
| OBS-001 轨迹查询 | 展示步骤、工具、错误、usage、耗时与估算成本 | P0（V1） | REL-001 | src/kernellens/observability/、src/kernellens/api/、tests/integration/test_traces.py | 可从失败追溯到步骤和输入摘要；敏感内容受控 | 日志、trace 与定位瓶颈 |

## Epic VERIFY / DEP：V1 交付 → 反馈与部署

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| VERIFY-001 服务器结果关联 | 导入人工执行结果并关联候选和 baseline | P0（V1） | OBS-001 | src/kernellens/verification/、tests/integration/test_verification.py | 代码、环境或工作负载不匹配不能证明当前候选通过 | Evidence 与实验有效性 |
| DEP-001 部署与 CI | 增加 ARM64 镜像、持久卷、CI 和运行手册 | P0（V1） | VERIFY-001 | Dockerfile、.dockerignore、.github/workflows/、docs/operations.md | 干净部署通过；重启后记录可读；发布前访问控制与资源限制明确 | 可复现交付与运行可靠性 |

## Epic OPT：V2 扩展 → 经过测量的改进

| ID / Task Name | Description | Priority | Dependency | Files | Acceptance Criteria | Learning Goal |
| --- | --- | --- | --- | --- | --- | --- |
| OPT-001 单变量优化 | 按瓶颈选择检索、模型、缓存或框架实验之一 | P2 | DEP-001、明确实验假设 | 相关实现、evals/reports/、按需 ADR | 同条件对照；报告回归和成本；无收益不必合入实现 | 实验与架构取舍 |
| GPU-001 受控执行器 | 有环境和需求后设计自动编译／执行／检测 | P2 | DEP-001、服务器权限和隔离方案 | src/kernellens/execution/、对应集成测试与 ADR | 隔离、资源／时间限制、结果归属和失败终止可验证 | 执行安全与真实硬件集成 |

## 当前学习单元：TOOL-001A

Phase 2 已提交为 `df1fee6 feat: implement bounded agent execution loop`，开始本单元前工作区干净。
当前进入 Phase 3；Pydantic 安装后原有 326 个测试仍通过，参数模型待用户实现。

- Task ID / Name：TOOL-001A / Report Tool Arguments & JSON Schema。
- Description：为后续 read_report 定义输入边界，由同一份声明校验参数并导出 JSON Schema。
- Priority / Dependency：P0；RUN-002 已提交，Phase 2 已完成；Pydantic 2.13.5 原生 ARM64 已验证。
- Files：用户新增 src/kernellens/tools/arguments.py 与 tests/test_tool_arguments.py；助手处理 pyproject.toml、uv.lock、空 tools/__init__.py、docs/tool-arguments.md、专项图、ADR 001 与相关文档。
- 助手已处理：依赖安装、版本锁定、ARM64 检查、原有测试回归、讲义参考代码 AST/Ruff 与示例语法；没有写入参数模型或新测试。
- Acceptance Criteria：path 必填且为包含非空白字符的严格字符串，保留原文；拒绝未知字段和普通赋值；导出 Schema 包含对应类型、必填、长度、pattern 与额外字段规则；通用行动合法不等于工具参数合法，参数合法不等于路径获授权；不访问文件。
- Tests：参考代码 6 个测试函数、预期 16 个用例，完整回归目标 342 = 326 + 16，尚未实测；检查 lint/format、Schema 与错误类型观察。
- Learning Goal：工具专属输入、严格校验、单一声明与 Schema 导出、数据和规则、参数形状和执行授权的边界。
- 参考实现及测试见 [tool-arguments.md](tool-arguments.md)；依赖选型与验证见 [ADR 001](decisions/001-tool-input-schemas.md)。
- Git Milestone：用户实现并验收后提交 `feat: add report tool argument schema`，包含模型、测试、包入口、依赖和文档；随后再建立工具定义与注册机制。

所有任务开始时再次核对实际文件；路径和接口需要调整时先更新设计，不能为了维持旧计划忽略代码事实。
