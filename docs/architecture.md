# 系统架构与运行契约

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

状态：目标设计；具体类型和接口在对应学习单元设计、由用户实现。本文不是已实现 API 文档。产品验收以 [product.md](product.md) 为准。

## 总体结构

采用模块化单进程应用：确定性流程包围有限的单 Agent 循环。CLI 先进入应用层，V1 API 复用相同应用入口。业务模块先用普通 Python 调用通信，不引入网络消息总线。

目标图见 [系统架构](diagrams/README.md#system-architecture) 和 [运行流程](diagrams/README.md#agent-runtime)。所有图源单独保存在 diagrams 目录。

| 模块 | 责任 | 明确边界 |
| --- | --- | --- |
| 应用层 | 校验任务入口、建立 run、调用 Runtime、返回报告 | 不包含模型推理逻辑 |
| Runtime | 循环、状态转换、预算、取消与终止 | 不绑定 provider 或具体算子工具 |
| Model Adapter | 发送模型输入、解析响应、关联 tool call、归一 usage | 使用 provider 官方客户端；保留原始响应引用 |
| Context Builder | 为当前步骤挑选目标、事实、证据和观察 | 不是把所有聊天和日志直接拼接 |
| Planner / Router | 提出简短计划、选择工具或下一步行动 | 初期是 Runtime 内的逻辑，不单独部署服务 |
| Tool Registry | 保存名称、版本、Schema、执行入口及风险分类 | 模型只能看到当前被允许的工具 |
| Tool Executor | 校验、限制路径、执行、超时、规范化结果 | 工具存在不代表当前任务有权限执行 |
| Evidence Retriever | 精确符号、关键词和元数据检索 | 命中记录不自动成为可信事实 |
| Artifact 管理 | 保存算子候选、报告与实验说明及内容标识 | 初期只写本次 run 的产物目录，不改用户源码 |
| State Store | 持久化状态、步骤、候选与证据引用 | MVP 保存；V1 才承诺显式恢复语义 |
| Report Verifier | 检查引用、需求覆盖和验证声明 | 不接受模型单方面宣布成功 |
| Trace | 将运行中的事实变成可查询步骤记录 | 不要求或依赖模型内部思维链 |
| Offline Evaluator | 对整个系统做案例评分及基线比较 | 与当前任务的 Report Verifier 分离 |

## 概念数据模型

此表描述待实现契约，不提前规定全部 Python 字段。

| 对象 | 必须表达的信息 | 设计目的 |
| --- | --- | --- |
| TaskRequest | generate / optimize / diagnose；计算语义；shape、dtype、布局；设备；精度、性能及权限约束 | 避免系统只理解错误日志任务 |
| TaskState | run 标识、目标、生命周期、预算、事实、假设、候选、证据和未解决问题 | 显式维护任务进展 |
| Action | 调用工具、请求信息或提交结果；短理由与相关证据 | 让决策可校验 |
| ToolCall | call 标识、工具名称／版本、参数、风险分类 | 关联请求与结果 |
| Observation | 执行状态、数据引用、业务检查结果、错误类别和是否允许重试 | 防止协议成功掩盖检查失败 |
| Evidence | 来源类型、源码 revision、路径／位置、内容标识、获取方式 | 固定证据所依赖的版本 |
| Candidate | 代码与内容标识、父候选／baseline、修改说明、验证计划 | 追踪生成、优化和修复演进 |
| VerificationRecord | 候选标识、环境、工作负载、检查方法、结果、原始产物、提供者 | 不把旧日志绑定到新代码 |
| Report | 交付内容、证据、风险、检查状态及下一步 | 输出可审阅结果 |

RUN-001A 将 TaskRequest 的第一版缩小为显式 TaskType 和非空 goal 原文，采用标准库枚举与 dataclass，在构造时校验。它只检查基本输入形式，不表示生成或优化所需材料已齐备。
上表的 shape、dtype、布局、设备等仍是目标信息契约，会在后续需求检查单元细化；运行标识、预算和结果属于 State。本单元参考代码见 [task-request.md](task-request.md)，实际实现状态见 docs/status.md。

## 两组状态必须分开

任务生命周期建议包括：pending、running、waiting_input、completed、failed、cancelled、budget_exhausted；V1 增加 interrupted 与显式恢复。

RUN-001B 采用上述七种状态，并先用 transition_status 纯函数校验转换。四种结束状态没有出口，同状态转换也拒绝；当前完整规则与边界见 [生命周期讲义](task-lifecycle.md) 和[专项图](diagrams/task-lifecycle.md)。
函数仅检查一条边是否合法；预算计量、补充输入是否有效、报告是否合格以及新状态保存，由后续 Runtime 与对应模块负责。生命周期代码的实际完成情况以 docs/status.md 为准。

验证按检查项记录：未运行、通过、失败、无法判断。例如语法、API 证据、编译、数值正确性、性能分别记录。另记录来源是用户提供、工具本地执行还是将来的服务器执行器。用户报告的成功不伪装成 Agent 亲自执行。

RUN-001C 先定义 VerificationStatus 与 VerificationState，五项检查默认 NOT_RUN，各自独立记录结果；拒绝混入生命周期枚举。INCONCLUSIVE 表示尝试过检查但无法可靠得出通过或失败结论，检查尚未执行则为 NOT_RUN。
本单元只校验结果表达的类型，不检查结果真实性；来源、候选、环境和原始证据在后续 VerificationRecord 中关联。具体契约见 [验证状态讲义](verification-state.md) 与[两维状态示例](diagrams/verification-state.md)，实际实现状态以 docs/status.md 为准。

任务 completed 表示交付满足当前任务契约。它不能推导出编译、正确性或性能均通过。

RUN-001D 将最小 TaskState 设计为 request、status、verification 三个字段的不可变快照，复用已有领域对象。transition_to 先校验生命周期边，再用 replace 返回只改变 status 的新快照，保留原请求和检查对象；不自动保存历史。
构造函数只校验当前字段类型，不能证明转换历史；后续 Runtime 通过 transition_to 更新生命周期，并单独执行业务验收。run ID、预算、候选及证据按消费需求逐步加入。
实现练习见 [TaskState 讲义](task-state.md) 与[更新图](diagrams/task-state.md)，实际代码进度以 docs/status.md 为准。

## 行动提议的输入边界

RUN-002A 先设计 RequestInputAction：固定 kind=request_input，question 和 reason 为非空字符串；reason 是面向用户的简短说明，不依赖模型内部思维链。
parse_request_input_action 接收已解码 Mapping，要求恰好包含 kind、question、reason，拒绝其他 kind，再通过对象构造校验文本。它不执行 JSON 解码，不判断提问必要性，也不展示问题或修改 TaskState；后续模型适配层与 Runtime 分别承担这些职责。
专用行动类避免把不同动作的字段混在一个任意 payload 中；调用工具与提交结果到对应单元再定义。补充信息行动已由用户实现并验收；Parser 显式缩窄局部变量类型，构造校验仍保护直接创建对象的路径。参考实现见 [补充信息行动讲义](request-input-action.md) 和[专项图](diagrams/request-input-action.md)。

RUN-002B 设计 CallToolAction 保存工具名、参数和目的。第一版参数为平坦标量映射：适用于计划中的源码检索／片段读取参数，拒绝嵌套容器与非有限浮点数；先复制再创建只读视图，避免输入别名或公开参数写入改写提议。实际工具需要复合参数时，再扩展契约与快照策略。
该类不检查工具是否注册，不判断具体参数是否适合目标工具，也不执行调用。工具 Schema、权限、调用标识和版本由对应单元完善；现有补充信息 Parser 不扩展为通用分派。该类已由用户实现并验收，参考实现见 [工具提议讲义](tool-call-action.md) 与[参数快照图](diagrams/tool-call-action.md)。

RUN-002C 设计 FinishAction 保存待提交 answer 与提交理由 reason，固定 kind=finish，构造仅检查文本形式并保留原文；提交提议不会修改 TaskState 或 VerificationState，也不证明交付满足需求。
AgentAction 通过模块级类型别名联合 RequestInputAction、CallToolAction 和 FinishAction，为后续接口声明行动集合；它不执行外部输入校验或分派。通用 Parser 与报告验收在对应单元实现。用户实现已通过 Review，参考实现见 [结果提交讲义](finish-action.md) 与[提交／完成边界图](diagrams/finish-action.md)，验收与提交状态见 docs/status.md。

RUN-002D 设计统一入口 parse_agent_action：接受已解码 Mapping，检查 kind 存在且为字符串，按 request_input / call_tool / finish 精确分派。每个分支要求完整且无额外字段，复用既有补充信息 Parser 和构造函数；未知标签明确拒绝，不默认完成，不修正标签或修改输入。
这是程序的协议分派，不是模型规划或工具执行。没有 JSON 解码、工具注册、权限检查、重试或状态更新；这些职责在对应单元接入。用户实现已验收，137 个测试及 lint/format 通过；参考实现见 [统一行动解析讲义](action-parser.md) 与[边界图](diagrams/action-parser.md)。

## 工具专属输入

TOOL-001A 先为后续 read_report 工具设计 ReadReportArguments：使用 Pydantic 2.13.5，从同一字段声明进行输入校验并导出通用 JSON Schema。path 必填、严格字符串、至少含非空白字符，保留原文；extra="forbid" 拒绝未知字段，frozen=True 限制普通赋值。CallToolAction 的通用标量校验不能替代工具参数校验；参数通过也不授权路径访问。后续执行器再检查访问范围与资源边界，Provider 适配时再核对 Schema 支持子集。
依赖及原生 ARM64 已验证，参数模型与新测试待用户实现；本轮没有工具注册、版本路由或实际文件读取。见 [参数讲义](tool-arguments.md)、[独立图](diagrams/tool-arguments.md) 与 [ADR 001](decisions/001-tool-input-schemas.md)。

## 工具反馈与检查结论

RUN-002E 先定义工具反馈 ToolObservation：关联原 CallToolAction，显式提供 ToolExecutionStatus（SUCCEEDED/FAILED）与非空 content 原文，可选 verification 为 VerificationState 或 None。它由后续程序侧适配器／执行器根据工具返回或异常构造，供 Runtime 消费；不让模型的提议直接变成执行证据。
读取报告的工具可以 SUCCEEDED，而报告中的 compilation 为 FAILED；执行状态、验证结论与任务生命周期分别维护。None 表示本次反馈不含检查报告；VerificationState() 表示这份报告明确记录各项 NOT_RUN，二者都不能覆盖任务已有结果。失败调用如保留部分检查信息，必须有实际来源，不能按状态自动生成或清除报告。
第一版借助不可变行动对象关联提议，尚无执行／尝试 ID，也不能区分同一提议的多次执行；错误分类、重试策略、来源与候选版本验证、报告合并在需要时加入。本类只校验结构与类型，不执行工具、不认证证据、不修改 TaskState。用户实现已验收，153 个测试及 lint/format 通过；参考实现见 [工具反馈讲义](tool-observation.md) 与[专项图](diagrams/tool-observation.md)。

## 运行与重新规划

RUN-003A 实现单次决策函数 decide_once：接收 RUNNING 的 TaskState、ToolObservation 的 tuple 和注入的 DecisionModel 可调用对象。所有输入检查通过后调用该对象一次，再复用 parse_agent_action 校验返回的 Mapping，返回行动提议。
这一层不执行行动、不更新生命周期或累计验证结果；模型及解析异常直接向调用者传播。tuple 限制序列的常规原地修改，但不核验反馈的任务归属、顺序或证据来源。单次函数调用尚不构成时间、Token 或循环预算；真实 Provider、上下文构造与错误策略后续接入。
用户实现已验收：171 个测试及 lint/format、运行观察通过；见 [一次决策讲义](runtime-decision.md) 和[专项图](diagrams/runtime-decision.md)。

RUN-003B 实现 DecisionBudget：正整数 max_decisions 与范围内的 used_decisions，均拒绝 bool；consume 在达到上限时抛出 DecisionBudgetExhausted，否则返回用量加一的新快照。run_agent 已在入口校验后、决策尝试前消耗额度并保存快照，失败不自动返还，耗尽后停止并更新生命周期。额度不等于真实 Provider 请求数或 Token 用量；预算对象本身不阻止调用者直接调用 decide_once，也不提供超时。用户实现已验收，190 个测试及 lint/format、运行观察通过；见 [预算讲义](decision-budget.md) 与[流程图](diagrams/decision-budget.md)。

RUN-003C 实现 apply_request_input：只接收 TaskState 与 RequestInputAction，复用 transition_to(WAITING_INPUT) 返回新快照。当前状态表仅允许 RUNNING 进入等待，规则不在 Handler 中重复维护；请求与检查结果保留。run_agent 已保存最新状态，并在步骤记录中保留原行动的问题与理由；后续应用层负责展示，当前没有待回答内容的持久化或输入恢复。组合测试验证等待态进入 decide_once 时不会调用模型，循环测试进一步验证等待后不再发起下一次调用。用户实现已验收，206 个测试及 lint/format、运行观察通过；见 [处理讲义](request-input-handler.md) 与[专项图](diagrams/request-input-handler.md)。

RUN-003D 实现 apply_finish：接收 TaskState、FinishAction 与程序侧显式注入的 FinishReviewer。先复用 transition_status 检查完成转换是否合法，再调用 reviewer 一次；严格 True 才通过 transition_to 返回 COMPLETED，False 抛 FinishRejected，非 bool 抛 TypeError，审核异常原样传播，不默认接受或重试。请求及 verification 保留，完成不推导出算子检查通过。当前只建立审核控制边界，测试用固定结果替身；真实报告审核、来源校验、结构化拒绝原因与反馈恢复后续实现。模型不能通过输出 accepted 字段装配审核依赖。用户实现已验收，全量 229 个测试及 lint/format、运行观察通过，已提交为 `4b8cdff`；见 [完成处理讲义](finish-handler.md) 与[审核流程图](diagrams/finish-handler.md)。

RUN-003E 实现 apply_call_tool：只在 RUNNING 接收 CallToolAction 与程序侧注入的 ToolExecutor，前置校验后调用 executor(action) 一次；返回必须是 ToolObservation，且 observation.action is action。类型正确但关联另一个 Action 的反馈被拒绝，包括字段完全相同的新对象；此约定只关联原对象，不认证来源或区分同一 Action 的不同执行尝试，跨进程和重试标识后续设计。SUCCEEDED/FAILED 反馈原样返回，执行异常传播不重试；不改变 TaskState 或合并验证报告，调用者显式收集并传给 decide_once。当前只用本地替身，不提前实现 Registry、工具路径校验、超时或真实执行；用户实现已验收，全量 256 个测试及 lint/format、运行观察通过，已提交为 `2048b96`；见 [工具行动讲义](tool-call-handler.md) 与[反馈关联图](diagrams/tool-call-handler.md)。

RUN-003F 实现冻结的 StepRecord，保存 decision_number、state_after、可选 action/observation/error，供有限循环记录每次尝试的处理结果。序号必须是正整数且拒绝 bool；至少有行动或错误，工具行动必须有反馈或错误，反馈须关联记录中的原 Action 且与 error 互斥。模型／解析失败允许没有 Action；正常返回的 FAILED 反馈仍属于 Observation。记录不执行行动、修改状态、消耗预算或合并报告，也不认证事件和转换历史；编号顺序、预算及请求关联现由 RunResult 检查。当前由 run_agent 自动创建进程内记录，尚未落盘或接入完整 Trace；本单元验收时全量 282 个测试及 lint/format、快照观察通过，已提交为 `526412f`；见 [步骤记录讲义](step-record.md) 与[独立图](diagrams/step-record.md)。

RUN-003G 实现冻结 RunResult，组合停止时的 TaskState、最新 DecisionBudget 和完整 StepRecord tuple。拒绝 PENDING/RUNNING；记录数必须等于 used_decisions，序号从 1 连续，所有记录引用同一 TaskRequest 对象。BUDGET_EXHAUSTED 要求额度用尽，反过来额度用尽可以同时对应已完成的任务。预算停止前没有新尝试时不应生成新记录，最后步骤状态可为 RUNNING，结果为 BUDGET_EXHAUSTED。当前仅校验类型与已列出的集合关系，不认证完整执行、交付审核或同请求的不同 run，也不支持只传增量历史；run_agent 负责实际控制语义。用户实现与 22 个新用例已验收，全量 304 个测试及 lint/format、汇总观察通过，已提交为 `8b7ccf5`；见 [结果汇总讲义](run-result.md) 与[独立图](diagrams/run-result.md)。

RUN-003H 实现 run_agent(state, *, budget, model, executor, reviewer) -> RunResult，作为新运行的单一协调函数。入口先校验 PENDING、零用量预算及三个可调用依赖；只在 RUNNING 消费并保存额度，再调用 decide_once 与已有 Handler，处理后统一追加 StepRecord。正常工具反馈（包括 FAILED）进入下一轮输入；请求信息和审核接受分别进入 WAITING_INPUT / COMPLETED；尝试中的 Exception（包括审核拒绝）保存 FAILED 与错误，不自动重试。预算耗尽发生在尝试之外，不新增记录；退出时由 RunResult 校验完整历史。入口异常与记录不变量异常直接暴露，KeyboardInterrupt 等 BaseException 不转换成结果。次数上限不提供回调超时、Token 控制、反馈大小限制、输入恢复或持久化；verification 不自动合并。用户实现和 22 个新用例已验收，全量 326 个测试及 lint/format、自动循环观察通过，已提交为 `df1fee6`；见 [有限循环讲义](agent-loop.md) 与[独立图](diagrams/agent-loop.md)。

以下是后续业务接入后的目标流程；当前尚无 Context Builder、真实工具和业务报告审核：

1. 应用层明确任务类型、输入缺口、允许访问的材料及预算。
2. 确定性检查确认基础条件，不能把关键证据失败隐藏成成功。
3. Context Builder 挑选这一轮需要的材料。
4. 模型提出结构化行动，程序校验并决定是否执行。
5. 工具结果形成 Observation：事实、失败及未运行检查都显式返回。
6. Runtime 更新状态；生成任务可修改候选，优化任务可修改假设，诊断任务可改变调查方向。
7. Report Verifier 判断能否结束；缺口作为新 Observation 返回，仍受同一预算控制。

禁止递归开启无预算的新任务来逃避当前预算。未知工具、非法参数和反复无进展都要有可测试出口。

## Context、Memory 与证据

- 指令和任务约束始终与源码、日志等不可信内容分隔；后者不能授权新工具。
- 完整输出留在产物中；上下文保存摘要、证据 ID、关键原文和必要的近期步骤。
- 裁剪时优先保留任务约束、最新候选、验证失败和阻塞项，不只保留最近聊天。
- 工具调用与结果必须配对，不能因裁剪破坏 provider 要求的消息结构。
- 任务记忆首先是结构化事实和来源，不是通用长期聊天记忆。
- 跨任务记忆后置：仅经确认的案例进入，保留版本范围、失效与纠错机制。
- RAG 初期以符号与元数据为主；是否增加 embedding 用检索指标决定。

## 三种产品路径

生成：明确需求 → 检索模式和 API → 构造候选 → 静态检查 → 测试与实验说明。

优化：确认计算契约与 baseline → 提出瓶颈假设 → 查证可行变更 → 构造候选 → 对照实验说明。

诊断：确认症状 → 查阅相关证据 → 支持／排除假设 → 修复候选或要求补充信息。

三条路径共享 Runtime、工具、状态与报告机制，不因此拆成三个 Agent。

## 手动执行与后续自动执行

初期用户在服务器执行算子。V1 导入结果时核对代码内容标识、源码／编译环境、设备、输入参数和测试方法；不匹配则保留原始记录并标记无法用于当前候选验收。

V2 才考虑执行器。Mac 上的 Agent 环境与 Linux GPU 执行环境独立管理；自动执行必须具备隔离、超时、资源及网络限制。普通 subprocess 或 Docker 本身不能替代完整执行边界设计。

## 持久化与服务边界

MVP 用 SQLite 保存运行和步骤，先单写入者。V1 的 API 仍限定单实例与有限并发。服务崩溃后明确标记 interrupted，由用户显式恢复；不把进程内后台任务称为持久队列。

恢复必须核对候选、工具、模型和证据版本。只读动作允许受控重放；有副作用的动作需使用操作标识及结果核对。没有相应协议时不声称 exactly-once。

## 目录演进

当前实际源码包括可安装的 src/kernellens 包与 config.py；domain/ 下已有 task.py、state.py、verification.py、action.py、observation.py；runtime/ 下已有 step.py、budget.py、handlers.py、records.py 和 loop.py。
handlers.py 当前实现请求信息处理、完成审核与工具行动处理；执行依赖和模型仍使用本地测试替身，tools/ 当前只有空 __init__.py。records.py 已有 StepRecord 和 RunResult，对应 tests/test_step_record.py 与 tests/test_run_result.py 已验收；RUN-003H 的 loop.py 与 tests/test_loop.py 也已验收，最近全量共 326 个测试通过；具体状态以 docs/status.md 和 Git 为准。

TOOL-001A 的 tools/arguments.py 和 tests/test_tool_arguments.py 尚未创建；Pydantic 已加入运行依赖。models、evidence、context、storage、evals 等目录在对应任务开始后创建；工具执行接口仍使用替身，尚无真实算子工具。

旧项目不通过相邻目录路径成为隐式运行依赖。引入素材或 MCP 时分别设计版本、许可、返回值及适配边界。重要取舍落地时才创建 ADR。
