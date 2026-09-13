# Phase Roadmap

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

这是研发路线，不是要求一次执行的操作清单。当前工作以 [当前能力与验证范围](status.md) 为准。
每个 Phase 拆成多个学习单元；每个单元都需要运行或检查、用户验收和 Checkpoint。
具体任务见 [Backlog](backlog.md)，关系见 [开发流程](diagrams/README.md#development-flow) 与 [依赖图](diagrams/README.md#dependency-graph)。

## Phase 0 — Requirement & Research

- Goal：确定真实需求、Agent 必要性、范围及学习方式。
- Tasks：定义生成、优化、诊断与验证反馈；比较替代方案；明确 M4 与服务器执行边界。
- Dependency：已有项目分析与用户约束。
- Concepts：任务契约、业务假设、Agent 与 Workflow 的区别。
- Implementation：设计评审；设计材料在 FND-002 归档。
- Deliverables：产品、架构和技术方向；MVP/V1/V2。
- Definition of Done：用户确认开始；核心逻辑由用户手写；初期不自动运行算子。
- Tests：场景走查；识别未决模型、预算、许可与环境问题。
- Git Milestone：确认后进入独立仓库；不把聊天当正式代码状态。
- Resume Value：解释为什么需要 Agent 以及为什么不用更复杂方案。

## Phase 1 — Project Foundation

- Goal：建立独立、可恢复、可复现的项目基础。
- Tasks：FND-001 独立 Git；FND-002 文档与图源；FND-003 原生环境；FND-004 工程配置。
- Dependency：Phase 0 已确认。
- Concepts：repository、虚拟环境、模块入口、配置与 pytest。
- Implementation：基础文件与文档；随后才引入 pyproject、包入口、lint 和测试配置。
- Deliverables：独立 Git、项目状态文件、设计文档、可复现环境。
- Definition of Done：Git Root 正确；依赖安装在项目环境；基础命令可从干净环境复现。
- Tests：文档链接和图源同步；解释器架构；配置与基础测试入口检查。
- Git Milestone：初始化、设计归档、环境配置分别形成可解释提交。
- Resume Value：工程复现与维护能力，不包装成 Agent 算法创新。

## Phase 2 — State & Minimal Runtime

- Goal：用户能解释并实现一次有界的 Agent 循环。
- Tasks：RUN-001 任务与状态；RUN-002 行动／观察；RUN-003 FakeModel 循环。
- Dependency：Phase 1。
- Concepts：state、action、observation、终止条件、结构化输出。
- Implementation：用户手写有限循环及核心契约；只用最小工具替身，不提前写完整 Registry。
- Deliverables：可运行的确定性 Runtime 示例与状态轨迹。
- Definition of Done：正常结束、请求信息、无效行动、预算耗尽均有明确行为。
- Tests：无需网络的状态转移与停止条件测试；禁止模型自行绕过预算。
- Git Milestone：`feat: add agent state contracts`；`feat: add bounded agent runtime`。
- Resume Value：可以讲清楚框架内部 loop 的职责；此阶段尚非完整产品。

## Phase 3 — Models & Controlled Tools

- Goal：接入真实模型，并可靠执行受限工具调用。
- Tasks：TOOL-001 契约和 Registry；TOOL-002 执行器；MOD-001 provider；MOD-002 集成。
- Dependency：Phase 2；真实调用前确定模型、数据范围与预算。
- Concepts：JSON Schema、call ID、参数校验、异步、超时与重试。
- Implementation：用户实现工具与模型边界；先少量只读工具，真实 API 调用显式启用。
- Deliverables：可观察的真实 tool-calling loop。
- Definition of Done：错误工具、非法参数、超时和限流可解释；协议成功不掩盖业务失败。
- Tests：FakeModel 故障注入、执行器测试、可选付费 API 集成测试。
- Git Milestone：`feat: add controlled tools`；`feat: integrate model tool calling`。
- Resume Value：工具编排、契约设计与外部依赖失败处理。

## Phase 4 — Evidence, Product Paths & Context

- Goal：把循环变成能生成、优化和诊断基础 GEMM 的产品。
- Tasks：EVD-001/002 证据与检索；DEV-001/002/003 三条路径；CTX-001 上下文；STO-001 记录。
- Dependency：Phase 3；引入知识前核对来源、许可和源码 revision。
- Concepts：grounding、RAG、候选版本、事实与假设、context budget、任务记忆。
- Implementation：用户实现证据、候选和报告逻辑；只在 run 产物目录保存候选。
- Deliverables：三类任务的 CLI 交付；测试／实验说明；证据及候选关联；持久记录。
- Definition of Done：关键 API 和引用可定位；报告区分未运行检查；上下文大小有界。
- Tests：源码缺失、版本漂移、API 缺口、设备冲突、中文术语、上下文裁剪与三个产品路径。
- Git Milestone：按证据、生成、优化、诊断与上下文拆分功能提交。
- Resume Value：代码生成可靠性、Context Engineering、证据约束与优化实验设计。

## Phase 5 — Evaluation & MVP Acceptance

- Goal：用数据评估系统，并完成 MVP 验收。
- Tasks：EVAL-001 案例与基线；EVAL-002 指标与回归；修复由评测发现的问题。
- Dependency：Phase 4；案例与验收草案从 Phase 0 起维护，不能最后才定义成功。
- Concepts：baseline、held-out cases、评分 rubric、消融、重复评测。
- Implementation：用户实现核心评分与对照逻辑；基础统计与报告胶水可由助手协助。
- Deliverables：单次 LLM、固定 Workflow、Agent 的对照报告及失败归因。
- Definition of Done：三个产品路径均有验收案例；关键不变量回归通过；报告可复现。
- Tests：确定性契约检查与语义评测分开；记录回放和真实运行分开统计。
- Git Milestone：`test: add agent evaluation baseline`；完成后才考虑 MVP release。
- Resume Value：以真实结果讨论质量、成本与延迟取舍；没有数据就不写提升指标。

## Phase 6 — Service, Recovery & Observability

- Goal：把 MVP 提供为可操作、可恢复的服务。
- Tasks：SVC-001 API；REL-001 恢复／取消；OBS-001 轨迹查询和成本视图。
- Dependency：MVP 验收；已有 run/step 记录，不重新发明一套状态。
- Concepts：任务生命周期、幂等、checkpoint、取消传播、trace/span。
- Implementation：用户实现核心恢复逻辑；普通接口胶水可由助手处理；维持有限并发。
- Deliverables：任务接口、显式恢复与取消、步骤查询、usage 和错误分类。
- Definition of Done：中断可识别；恢复不误认已完成动作；使用量未知时明确显示未知。
- Tests：进程中断、重复请求、取消、版本改变及状态查询的一致性。
- Git Milestone：`feat: add resumable task service`；`feat: expose run traces`。
- Resume Value：运行可靠性与可观测性；不夸大为分布式高并发系统。

## Phase 7 — Verification Feedback & Deployment

- Goal：形成可部署的人工参与验证闭环并交付 V1。
- Tasks：VERIFY-001 服务器结果导入；DEP-001 容器、CI、运行手册。
- Dependency：Phase 6；结果样例、执行环境描述和发布权限。
- Concepts：结果归属、实验可比性、数据来源、部署与持久化。
- Implementation：用户实现验证契约与判断；助手可处理 Docker/CI 重复配置。
- Deliverables：代码与测试结果关联、性能对照、ARM64 镜像、运行与恢复说明。
- Definition of Done：干净环境部署通过；错误版本的结果不能验证当前候选；人工执行来源可见。
- Tests：hash/环境/工作负载不匹配；容器启动；持久卷重启；不需要 GPU 的 CI 回归。
- Git Milestone：`feat: complete verification feedback`；`chore: add deployment checks`。
- Resume Value：从需求到候选到实测反馈的产品闭环及可复现交付。

## Phase 8 — Measured Optimization & Extensions

- Goal：根据真实瓶颈优化系统，不预设扩展必做。
- Tasks：OPT-001 单项实验；GPU-001 受控执行器（有需求与环境才做）。
- Dependency：已有固定基线；每次实验明确变量、收益假设及预算。
- Concepts：成本／延迟优化、框架取舍、缓存失效、执行隔离。
- Implementation：用户实现 Agent 核心变更；不在同次实验同时改 Prompt、模型和检索。
- Deliverables：可复现实验报告；有证据的改进或否定结论。
- Definition of Done：效果与回归风险可核验；执行器上线前通过权限与隔离检查。
- Tests：保留评测集、失败与资源边界、按能力选择的真实硬件验证。
- Git Milestone：以实际变化命名功能分支与提交；无收益的实验可保留报告而不合入实现。
- Resume Value：真实技术难点、量化效果和失败经验；支持 Junior → Senior 面试追问。

## 提交与评审

按完整的小功能提交；不要每个文件一提交，也不要把整个 Phase 压成一个巨大提交。用户执行提交，助手给出范围与理由。需要练习企业协作时，再采用 `codex/<task>` 分支 → 开发 → 测试 → Review → Merge，不为文档初始化引入额外流程。

每个单元的完成记录压缩进 docs/status.md。未来的预估与目录只存在于设计文档，相关任务开始前不创建实现占位。
