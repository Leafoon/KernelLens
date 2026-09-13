# 开发与学习指南

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

本项目按 Mentor-Driven Incremental Development 推进。协作约束见 [贡献指南](../CONTRIBUTING.md)，当前任务以 [当前能力与验证范围](status.md) 为准。

## 学习起点与职责

用户熟悉 Python 基础，但尚未独立完成工程项目。类型标注、模块、异常、pytest、虚拟环境和 Git 都结合当前功能解释，不要求先完成一套无关课程。

助手同时承担 Tech Lead、Architect、Engineer、Project Manager、Reviewer 和导师职责。目标是让用户能解释和修改真实实现，不能只交付一份生成好的代码仓库。

| 工作 | 用户 | 助手 |
| --- | --- | --- |
| Runtime、State、Tool Calling、Context、RAG、恢复、模型边界、Evaluator | 理解设计、亲手实现、运行并观察 | 解释、给当前单元参考代码、评审、带领定位 |
| 核心测试与验收判据 | 理解并实现关键断言 | 帮助设计有效测试，不用镜像实现的断言充数 |
| 文档、配置、入口、重复类型和脚本 | 理解用途并审阅 | 可直接处理机械部分，说明修改内容 |
| Git | 观察状态、选择提交、练习分支和合并 | 检查边界、建议提交范围与 message |

不确定是否属于核心逻辑时：如果影响 Agent 决策、状态、执行、上下文、恢复或验收，默认由用户实现。

## 每个学习单元的八步

| 步骤 | 本轮应发生什么 | 用户需要得到的理解 |
| --- | --- | --- |
| Context | 说明 Phase、已完成内容、当前目的和依赖 | 为什么现在做 |
| Concept | 解释必要概念及其解决的问题 | Why，而不只是 How |
| Design | 先讨论输入、输出、接口、状态和控制流 | 代码背后的契约 |
| Implementation | 给出当前文件位置和当前逻辑；用户输入核心代码 | 亲手把设计转成实现 |
| Run | 给出命令与预期结果 | 从源代码到实际行为 |
| Observe | 查看输出、日志、工具输入、Observation 和 state | 系统实际发生了什么 |
| Debug | Problem → Evidence → Hypothesis → Verification → Fix | 根据证据定位，而不是盲改 |
| Checkpoint | 总结、更新状态文件、说明 Git 节点后暂停 | 明确完成和未完成内容 |

参考代码只覆盖当前单元。即使未来模块很容易顺手创建，也保留到未来 Task。用户说“帮我检查”时先做评审；有问题则指导用户修复，不直接实现后续任务。

## 如何观察 Agent

重点观察：用户目标是什么、当前计划是什么、模型提出了哪个工具、实际参数是否合规、工具结果与业务检查状态是否不同、哪条新证据改变了假设、为什么继续或停止。

可解释性来自行动、证据与状态，不依赖模型暴露内部思维链。以“工具没有抛异常，但返回业务失败”为例，应从 Observation 到报告检查器逐层追踪，不能只看最终文本。

## 概念路线与任务路线

[学习路径图](diagrams/README.md#learning-path) 展示概念关系；[roadmap.md](roadmap.md) 决定真实实施顺序。
概念会反复出现：先用 FakeModel 学会循环，随后接真实工具；先保存状态，之后才学习恢复；先理解评分，再做框架或模型优化。

## Git 练习

- `git status` 查看工作区与暂存状态；`git diff` 查看已跟踪内容的修改。
- 新文件尚未跟踪时不会出现在普通 diff 中；先阅读文件，再明确选择需要暂存的文件。
- `git add` 选择提交内容；`git diff --cached` 检查暂存快照；`git commit` 保存本地历史。
- 一个 Commit 对应完整、可解释、可验证的小单元。不要每改一文件就提交。
- 后续适当阶段练习 `codex/<task>` 分支、开发、测试、Review 和 Merge。
- 内层和外层仓库独立；使用本项目根目录运行 Git，不在外层暂存 kernellens-agent。
- 提交失败时保留报错再定位，不预先修改全局 Git 身份或配置。

## Git Checkpoint

RUN-003H 已提交为 `df1fee6 feat: implement bounded agent execution loop`，Phase 2 已完成。当前 TOOL-001A 的依赖与工程准备已处理，参数模型与新测试待用户输入；以下 Git 流程在本单元 Review 和验收后执行，现在先完成 [工具参数练习](tool-arguments.md)。

工作区是正在编辑的文件；暂存区是选给下一次提交的内容；提交历史是已经保存的快照。
`git commit` 保存暂存区，如果暂存后又改了文件，新改动需要再次暂存才能进入同一提交。

在 `kernellens-agent` 根目录，先确认仓库边界，再暂存当前已审阅的变更：

```bash
git rev-parse --show-toplevel
git add -A -- .
git diff --cached --stat
git diff --cached
```

Git Root 应是内层 `kernellens-agent`。TOOL-001A 验收后，暂存范围应包含 tools/arguments.py、tests/test_tool_arguments.py、空包入口、pyproject.toml、uv.lock、讲义、专项图、ADR 与相关文档，不应包含 `.venv`。
`git diff --cached` 会展示暂存区的实际内容；若打开分页器，按 `q` 退出。
只有核对过全部变更范围后才暂存整个项目；混有其他工作时应按文件或变更片段选择。

范围正确后由用户执行：

```bash
git commit -m "feat: add report tool argument schema"
git status
git log -1 --oneline
```

预期：工作区干净，最新提交信息与上面一致。`commit` 仅保存本地历史，没有向 GitHub 推送。
如有报错，先保留错误与 `git status` 输出，根据证据定位，不直接重置仓库或修改全局配置。
这个 Checkpoint 完成后，用户确认，再进入当前单元的下一步，具体以 docs/status.md 为准。

## 项目文档各自保存什么

| 文件 | 权威范围 |
| --- | --- |
| docs/status.md | 当前阶段、已完成内容、证据与下一步；保持简洁 |
| AGENTS.md | 导师协作和核心代码边界 |
| docs/product.md | 产品范围和业务验收 |
| docs/architecture.md | 模块和运行契约 |
| docs/technology.md | 选型理由、兼容性与待验证事项 |
| docs/roadmap.md | Phase 和阶段验收 |
| docs/backlog.md | Epic、Feature、Task 及学习目标 |
| docs/quality.md | 测试、评测、观测和风险策略 |
| docs/environment.md | 原生环境、包安装、导入观察和验证记录 |
| docs/configuration.md | 当前配置与测试练习；参考代码不代表已实现 |
| docs/task-request.md | RUN-001A 的输入契约、用户实现与测试练习 |
| docs/task-lifecycle.md | RUN-001B 的状态转换设计与测试练习 |
| docs/diagrams/task-lifecycle.md | 生命周期专项图的唯一图源，独立预览 |
| docs/verification-state.md | RUN-001C 的验证状态契约与测试练习 |
| docs/diagrams/verification-state.md | 任务完成与验证结果的专项示例图 |
| docs/task-state.md | RUN-001D 的最小状态组合、快照更新及测试练习 |
| docs/diagrams/task-state.md | TaskState 组合与更新的唯一图源 |
| docs/request-input-action.md | RUN-002A 的具体行动与外部输入解析练习 |
| docs/diagrams/request-input-action.md | 行动解析与后续执行边界的唯一图源 |
| docs/tool-call-action.md | RUN-002B 的工具提议、参数所有权和只读快照练习 |
| docs/diagrams/tool-call-action.md | 参数快照构造流程的唯一图源 |
| docs/finish-action.md | RUN-002C 的结果提交提议与行动联合类型练习 |
| docs/diagrams/finish-action.md | 提交提议与后续验收流程的唯一图源 |
| docs/action-parser.md | RUN-002D 的统一解析入口、分派、校验与测试练习 |
| docs/diagrams/action-parser.md | 解析流程与后续执行边界的唯一图源 |
| docs/tool-observation.md | RUN-002E 的工具反馈、执行状态和可选检查报告练习 |
| docs/diagrams/tool-observation.md | 工具反馈与检查结论的独立图源 |
| docs/runtime-decision.md | RUN-003A 的单次决策、依赖注入、测试与运行观察 |
| docs/diagrams/runtime-decision.md | 单次调用、解析与后续行动执行边界的独立图源 |
| docs/decision-budget.md | RUN-003B 的次数预算、耗尽异常、边界测试与运行观察 |
| docs/diagrams/decision-budget.md | 预算快照、次数边界和未来停止处理的独立图源 |
| docs/request-input-handler.md | RUN-003C 的请求信息处理、状态机复用及组合测试 |
| docs/diagrams/request-input-handler.md | 行动应用、等待快照和后续调用边界的独立图源 |
| docs/finish-handler.md | RUN-003D 的完成审核接口、拒绝／异常路径及组合测试 |
| docs/diagrams/finish-handler.md | 程序审核、完成快照与验证结论保留的独立图源 |
| docs/tool-call-handler.md | RUN-003E 的执行接口、反馈归属、失败路径及组合测试 |
| docs/diagrams/tool-call-handler.md | 工具调用与原 Action 关联校验的独立图源 |
| docs/step-record.md | RUN-003F 的步骤结果、错误材料、关联规则及快照测试 |
| docs/diagrams/step-record.md | 一次尝试的结果组成与历史快照的独立图源 |
| docs/run-result.md | RUN-003G 的结果组合、记录数与预算、序号和请求关联 |
| docs/diagrams/run-result.md | 运行结果的集合一致性及预算停止的独立图源 |
| docs/agent-loop.md | RUN-003H 的逐步决策、预算门槛、自动记录和停止策略 |
| docs/diagrams/agent-loop.md | 有限循环与异常处理的独立图源 |
| docs/tool-arguments.md | TOOL-001A 的严格工具参数、Schema 导出与授权边界 |
| docs/diagrams/tool-arguments.md | 参数校验与规则导出的独立图源 |
| docs/decisions/001-tool-input-schemas.md | 参数 Schema 依赖选型与 ARM64 验证 |
| docs/diagrams/ 下五个独立 .md 文件 | mermaid 代码块是唯一图源；README.md 展示页从源生成 |

Git 保存详细历史；状态文件不保存完整聊天。ADR 只在真正做出长期架构决定时创建，采用 Context、Decision、Alternatives、Reason、Consequences，不预先生成几十个空决定。

## Context Recovery Protocol

1. 读取 docs/status.md。
2. 核对 Git Root、git status、git log、项目目录和关键代码。
3. 如果文档与实现冲突，以代码和 Git 的事实修正状态；用户最新明确范围仍然有效。
4. 简报 Current Phase、Current Task、Last Completed、Next Step、Git Status。
5. 只恢复当前单元需要的细节，避免重复整个背景。

## FND-002 的文档运行命令

在项目根执行 `python3 scripts/sync_diagrams.py` 生成展示页；执行 `python3 scripts/sync_diagrams.py --check` 检查同步状态。
这是仅使用标准库的文档脚本，可使用已有 Python，也可通过 uv run 在项目环境中运行；FND-003 的环境验证记录见 [environment.md](environment.md)。

只编辑五个独立 `.md` 图文件中的 `mermaid` 代码块，README.md 展示页自动生成。
在 VS Code 打开这些文件，按 `⌘⇧V`，或在命令面板选择 `Markdown: Open Preview to the Side`，查看图形。
格式采用 [Markdown Preview Mermaid Support 支持的 Mermaid 代码块](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid)，同时可用于 GitHub Markdown。
同步检查只能证明内容一致，不能证明 Mermaid 语法和最终布局；图的解析／渲染应另行核对并如实记录验证程度。

## 简历与面试的积累方式

每个真实功能记录问题、设计、关键代码、失败案例、检查与取舍。保存实际评测报告，最终再组织项目介绍和量化结果。
练习顺序：Junior 解释 loop 和工具；Mid-Level 解释状态、上下文和错误恢复；Senior 解释验收、成本、部署边界与架构取舍。
不以“使用了某框架”替代技术贡献，不提前填写成功率或加速比。

## 单元结束格式

```text
Current Phase:
Current Task:
Status:
You Learned:
Files Changed:
Test:
Git:
Next:
```

每个单元完成后暂停，当前验收状态以 docs/status.md 为准；任务请求、生命周期和验证状态分单元实现与验收。
