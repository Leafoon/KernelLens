# KernelLens Agent：功能、架构与方法原理详解

> 编写日期：2026-09-13。本文依据当前 `KernelLens` 源码和实际验收记录编写，面向具备 Python 基础、希望理解整个 Agent 工程的读者。
>
> 阅读时请区分三个层次：**程序已经实现的能力、提示词要求模型遵循的行为、需要源码或硬件实验才能证明的结论**。当前终端 Agent 已完成工程交付，模型生成的算子仍属于待验证候选。

## 阅读导航

1. [项目定位与核心概念](#overview)
2. [功能总览](#features)
3. [如何启动和使用](#usage)
4. [总体架构与模块分工](#architecture)
5. [一次任务如何完整运行](#execution)
6. [模型接口与行动协议](#model)
7. [领域对象与状态机](#state)
8. [工具系统与输入契约](#tools)
9. [工作区隔离与文件写入](#workspace)
10. [GEMM 静态声明检查](#gemm)
11. [交付审核与证据机制](#review)
12. [Prompt、上下文与检索](#context)
13. [会话、运行记录与持久化](#storage)
14. [补充输入、恢复与中断](#recovery)
15. [预算、超时与错误处理](#errors)
16. [服务器报告与性能比较](#reports)
17. [三个任务示例与真实观察](#examples)
18. [技术选型与工程方法](#engineering)
19. [已验证结果、局限与后续方向](#limits)
20. [源码阅读路线与术语表](#reading)

<a id="overview"></a>
## 1. 项目定位与核心概念

KernelLens 是一个在指定工作区内运行的终端 Agent，主要帮助用户完成 TileLang 算子开发中的三类任务：

- **生成**：根据计算需求形成算子候选，保存代码并提供验证说明。
- **优化**：读取已有实现，提出改动、保存新候选并说明对照实验。
- **诊断**：读取代码、日志或报告，解释问题并给出有依据的建议。

MVP 聚焦基础 GEMM，即矩阵乘法 `C = A × B`。可以把 M、N、K 理解为矩阵维度：A 的形状为 M×K，B 为 K×N，输出 C 为 M×N。本文介绍 Agent 如何处理这些需求，不提供已经验证的 TileLang 算子教程。

系统也允许一般代码阅读、文本整理和文档写入。它使用云端模型进行推理，在本机执行受约束的文件操作。Mac 可以运行 Agent；GPU 编译、正确性和性能实验由用户在对应服务器完成，再将报告放回工作区。

### 1.1 什么使它成为一个 Agent

模型一次回答可能提出“读取某个文件”。程序实际读取后，把工具反馈交给模型，模型再决定是否继续搜索、写入候选、请求信息或者完成任务。

```text
用户目标 → 模型提出行动 → 程序检查并执行 → 工具反馈
                 ↑                           │
                 └──────── 下一次决策 ────────┘
```

这个循环的关键是：后续行动会受到前一步结果影响。例如，文件不存在时需要重新列目录，语法失败时需要修改候选，证据引用缺失时需要补充回答。所有这些尝试仍受程序预算约束。

### 1.2 模型与程序各自负责什么

| 部分 | 负责的事情 | 不能据此推导的结论 |
| --- | --- | --- |
| 模型 | 理解需求、选择下一步、解释材料、生成候选与建议 | 模型说“正确”不能代替验证 |
| 工具执行器 | 访问工作区、校验输入、读写文件、解析代码和报告 | 读到报告不代表程序亲自执行了实验 |
| Runtime | 控制循环、行动分派、预算、状态与停止 | 运行停止不一定意味着任务成功 |
| 交付审核器 | 检查当前产物、静态检查和证据编号 | 编号存在不证明每句话都有充分依据 |
| 用户与服务器 | 确认专业结论、核对 API、执行 GPU 实验 | 外部结果需要正确关联到当前候选 |

目前是**单进程、单 Agent**。CLI、模型适配器、工具注册器和审核器是程序模块，不是四个独立 Agent；审核器使用确定性代码，不会再调用一个模型投票。

<a id="features"></a>
## 2. 功能总览

| 功能 | 用户可以做什么 | 当前实现方式 |
| --- | --- | --- |
| 工作区选择 | 启动后选择一个已有目录 | 终端选择器与 Workspace 对象 |
| 连续交互 | 多轮提出任务、补充信息 | CLI 输入循环与 SQLite 会话 |
| 明确任务类型 | 使用 `/generate`、`/optimize`、`/diagnose` | TaskType 与任务 Prompt |
| 文件调查 | 列目录、读片段、搜文本 | 工作区文件工具，返回路径、行号或哈希 |
| 产物生成 | 保存 Python 候选及 Markdown 文档 | write_file、哈希冲突检查与备份 |
| 静态检查 | 检查 Python 语法和可识别的 GEMM 声明 | AST 解析与有限的常量解析 |
| 优化候选 | 基于 baseline 形成新版本 | 读取 baseline、保存不同候选、审核声明一致性 |
| 报告反馈 | 读取服务器 JSON 报告并对比 | 代码哈希、比较条件和样本校验 |
| 输入恢复 | 回答问题后继续，失败后显式重试 | 同会话创建新 run，携带历史与原目标 |
| 可观察记录 | 查对话、运行、步骤与产物 | `/history`、`/runs`、`/trace` 与磁盘报告 |
| 模型适配 | 使用兼容 Chat Completions 的接口 | 原生工具调用或 JSON 行动模式 |
| 脚本集成 | 一次提交任务，获取 JSON 输出 | `--prompt`、`--json`、退出码 |
| 资源控制 | 限制决策、输出、上下文、请求等待和重试 | Runtime 预算与 HTTP 客户端约束 |

当前不提供任意 shell、自动运行用户 Python、自动 GPU Runner、Web 服务、多用户权限系统、向量数据库或多 Agent 编排。

<a id="usage"></a>
## 3. 如何启动和使用

### 3.1 环境与启动

项目使用 Python 3.12，运行依赖为 Pydantic 2.13.5，开发检查使用 pytest 9.1.1 和 Ruff 0.16.6。完整依赖版本由 [pyproject.toml](../pyproject.toml) 和 [uv.lock](../uv.lock) 管理。

在项目根目录执行：

```bash
uv sync --locked
uv run --locked kernellens
```

`uv sync --locked` 按锁文件同步环境；`uv run` 使用项目环境启动程序。命令名 `kernellens` 在 pyproject.toml 中映射到 `kernellens.cli:main`。也可以用 `uv run --locked python -m kernellens` 进入相同 CLI。

终端交互示意：

```text
选择工作区 workspace（回车使用当前目录；输入路径切换；q 退出）
workspace> /path/to/my-workspace

你> /diagnose 读取 compile.log 和 kernel.py，说明错误并引用证据。
你> /runs
你> /trace
你> /exit
```

工作区必须已经存在；路径可包含中文与空格。工作区是后续文件访问的边界，不要求它就是 KernelLens 的安装目录。

### 3.2 配置如何读取

配置包含 `base_url`、`model`、`api_key` 和各项预算。首次配置可参考 [.env.example](../.env.example)；已有 `.env` 时无需覆盖。

```dotenv
base_url=https://your-provider.example/v1
model=your-model-id
api_key=your-private-key
```

上面全部是占位值，不包含真实密钥。当前验收使用 `mimo-v2.5`；模型和供应商不是写死在业务代码里的。

优先级为：

```text
显式 CLI 参数 > 进程环境变量 > dotenv 文件 > 默认值
```

dotenv 从启动目录向上查找；可编辑安装还会尝试项目根目录。`--env-file` 可以显式指定配置文件，但环境变量仍有更高优先级。模型字段支持小写名称、全大写名称、`KERNELLENS_*` 和 `OPENAI_*` 别名；同一层中优先使用 `KERNELLENS_*`。

解析器支持引号、注释和 `export`，按字面读取，不执行 shell，也不展开环境变量。配置在启动时加载，因此修改后需要重新启动；切换工作区不会加载另一套凭证。

### 3.3 交互命令

| 命令 | 行为 |
| --- | --- |
| `/generate 需求` | 明确进入生成任务 |
| `/optimize 需求` | 明确进入优化任务 |
| `/diagnose 问题` | 明确进入调查、解释任务 |
| `/workspace [路径]` | 选择或切换目录，并创建该工作区的新会话 |
| `/new` | 当前工作区创建新会话 |
| `/sessions` | 列出最近会话 |
| `/resume ID` | 通过完整 ID 或唯一前缀恢复会话 |
| `/history` | 查看近期用户输入和回答 |
| `/runs` | 查看当前会话最近的运行 |
| `/trace [ID前缀]` | 查看最近或指定运行的步骤和反馈 |
| `/status` | 查看工作区、模型、模式及部分预算 |
| `/paste` | 输入多行任务，用独立一行 `/end` 结束 |
| `/help` | 显示命令帮助 |
| `/exit` | 退出并关闭数据库 |

直接输入自然语言时，`infer_task()` 使用关键词规则分类。例如“解释”优先走诊断，“优化”走优化；未命中规则时默认诊断。这是轻量规则路由，没有额外的分类模型。存在歧义时，使用显式斜杠命令最清楚。

### 3.4 单次执行与输出

```bash
uv run --locked kernellens \
  --workspace /path/to/my-workspace \
  --task diagnose \
  --prompt '读取 compile.log 并解释错误' \
  --json
```

设置 `--prompt` 后执行一轮并退出；不设置 workspace 时使用启动目录。设置 `--json` 后，最终结构化结果写到 stdout，进度写到 stderr，便于脚本分别处理。

结果字段包括：`run_id`、`session_id`、`status`、`answer`、`report_path`、`usage`、`artifacts`。正常运行的报告和产物路径相对工作区；启动或配置失败可能返回较简短的 `status/error` 对象。

`--doctor` 离线检查安装位置和配置是否齐全。`--check-api` 是显式的小型真实 API 请求，最多 128 输出 Token、不自动重试，可能计费。

<a id="architecture"></a>
## 4. 总体架构与模块分工

```text
终端用户
   │
   ▼
CLI：参数解析、工作区选择、命令与输出
   │
   ▼
AgentApplication：创建本轮运行，连接各个组件
   │
   ├── Store：会话、步骤、报告
   ├── DecisionAdapter ── ChatClient ── 云端模型
   ├── ToolRegistry ── Workspace ── 工作区文件
   └── run_agent ── Handler ── ReportReviewer
           │          │              │
           └── 状态、行动、反馈、预算与结束条件 ──┘
```

可视化控制流见 [CLI 运行图](diagrams/cli-agent.md)。该文件保存 Mermaid 图源，本文通过链接引用，避免再维护一份相同图源。

### 4.1 源码目录

```text
src/kernellens/
├── cli.py                  # CLI 参数、选择器与交互循环
├── __main__.py             # python -m kernellens 入口
├── application.py          # 组件装配、任务执行与报告
├── config.py               # 配置读取、优先级与校验
├── security.py             # 已知密钥脱敏与终端文本处理
├── prompts.py              # 模型行为要求与任务背景
├── constraints.py          # GEMM 声明提取和比较
├── review.py               # 完成提议审核
├── storage.py              # SQLite 与磁盘报告
├── domain/                 # Task、State、Action、Observation
├── runtime/                # 决策、Handler、预算、记录、循环
├── models/client.py        # HTTP 客户端与行动协议适配
└── tools/                  # 工具参数、注册器、文件及报告工具
```

### 4.2 关键类和方法

| 入口 | 输入与职责 | 输出或影响 |
| --- | --- | --- |
| `cli.main()` | 命令行参数与终端输入 | 启动会话、展示结果、返回退出码 |
| `choose_workspace()` | 默认目录与用户选择 | 有效 Workspace，错误时重新选择 |
| `load_settings()` | 环境、dotenv、显式覆盖项 | 已校验 Settings |
| `AgentApplication.run()` | session_id、goal、可选 TaskType | TurnResult 与持久记录 |
| `DecisionAdapter.__call__()` | 当前状态和累积反馈 | 通用行动字典 |
| `ChatClient.complete()` | messages 与工具 schemas | 模型 message、累计请求和 usage |
| `run_agent()` | 初始状态、预算及注入依赖 | RunResult |
| `ToolRegistry.__call__()` | CallToolAction | ToolObservation |
| `Workspace.read_file()` 等 | 已验证参数 | 文件或报告工具结果 |
| `ReportReviewer.__call__()` | 当前任务与 FinishAction | 接受或抛出 FinishRejected |
| `Store.step()` | run_id 与 StepRecord | 提交一个步骤到 SQLite |
| `Store.finish_run()` | 状态、回答、用量、证据与产物 | report.md、result.json 与运行终态 |

`AgentApplication` 的作用是“装配”：Runtime 不直接依赖某个供应商或数据库，而是接收可调用的 model、executor、reviewer。正式运行注入真实组件，测试时注入可控制的替身。

<a id="execution"></a>
## 5. 一次任务如何完整运行

假设用户输入：

```text
/generate 生成基础 GEMM，M=N=K=128，A/B/C float16，累加 float32。
```

应用会依次完成以下工作：

1. CLI 分出命令和需求，确定任务类型为 generate。
2. 应用检查非空输入和 20000 字符输入上限。
3. 读取近期会话；必要时将本次补充接到上一轮未完成目标后。
4. 检查需求、会话或配置中的目标 GPU；生成/优化缺失型号时创建 `waiting_input` 记录，直接询问，不调用模型。回复型号后继续原任务，并保存在会话中。具体入口、优先级与例子见 [CLI GPU 输入说明](cli.md#目标-gpu)。已具备必要设备信息后检查模型配置，创建 run_id，记录用户输入、任务目标和运行开始时间。
5. 提取可识别的 GEMM 显式约束，装配工具、模型客户端和交付审核器。
   CLI 默认加载随包知识库，任务相关时程序先做有界预检索，以已知目标后端为默认过滤，作为 decision 0 保存并加入首次模型请求材料。型号、后端与声明来源另行传入模型；不猜测硬件的具体指令能力。
6. 创建 PENDING 状态和未使用预算，进入 `run_agent()`。
7. 每次决策前先消费一次额度，再向模型请求一个行动。
8. 工具行动由 Registry 执行，反馈交给下一次模型决策；缺少输入则暂停；完成提议则审核。
9. 每完成一个步骤，调用 `on_step` 保存记录并显示进度。
10. 运行结束后，应用组合回答、程序检查摘要、证据索引和 usage，保存报告。

下面是用于理解控制流的伪代码，省略了异常、类型校验和记录细节：

```text
state = RUNNING
while state == RUNNING:
    消费一次决策预算
    action = 模型根据目标和反馈提出行动

    如果 action 是 call_tool:
        observation = 执行器校验并执行工具
        保存反馈，供下一步决策使用
    如果 action 是 request_input:
        state = WAITING_INPUT
    如果 action 是 finish:
        审核通过 → state = COMPLETED
        审核拒绝 → 将原因反馈给模型

    保存本步记录

保存最终状态、报告与产物索引
```

CLI 正式应用传入了审核拒绝回调，因此拒绝后可以继续纠正。单独复用底层 Runtime、没有提供该回调时，FinishRejected 会按异常记录并结束。这是现有接口的实际区别。

<a id="model"></a>
## 6. 模型接口与行动协议

实现入口：[models/client.py](../src/kernellens/models/client.py)。

### 6.1 HTTP 客户端负责通信

客户端使用 Python 标准库 `urllib`，向兼容的 Chat Completions endpoint 发送 POST 请求。请求包含 model、messages、max_tokens，以及 `stream=false`。当前界面显示步骤级进度，不提供逐 Token 流式输出。

如果 base_url 没有以 `/chat/completions` 结尾，配置对象会补上这一段；已经是完整 endpoint 的地址保持原样。客户端使用 Bearer 认证，拒绝自动重定向，响应读取上限为 2000000 字节。

通信层负责处理认证、限流、服务错误、连接问题、超时、响应 JSON 和 usage；它不决定具体读哪个文件。

### 6.2 原生工具调用模式

默认 `tool_mode=native`。程序把工具名称、用途和参数 Schema 放入请求，模型返回 tool_calls。

简化的模型消息示例：

```json
{
  "role": "assistant",
  "tool_calls": [
    {
      "id": "call_read_1",
      "type": "function",
      "function": {
        "name": "read_file",
        "arguments": "{\"path\":\"kernel.py\",\"max_lines\":80}"
      }
    }
  ]
}
```

注意 `function.arguments` 是一个包含 JSON 的字符串。适配器解析它，规范化为内部行动，执行后再发送带相同 `tool_call_id` 的 tool 消息。call ID 把“这次工具提议”和“这次返回结果”关联起来。

请求设置 `parallel_tool_calls=false`，但供应商或模型仍可能返回多个调用。当前程序会整体拒绝这批提议，为每个 call ID 返回纠正反馈，不执行其中一部分，以免模型和本机对已执行动作的理解不一致。

### 6.3 JSON 行动模式

配置 `--tool-mode json` 时，客户端不附加原生工具列表；工具说明与行动格式放进系统 Prompt，要求模型输出通用行动 JSON：

```json
{
  "kind": "call_tool",
  "tool_name": "read_file",
  "arguments": {"path": "kernel.py", "max_lines": 80},
  "reason": "检查已有实现"
}
```

两种协议最终使用相同的 Action、Runtime 和工具执行器。JSON 模式是显式配置选项，没有在 API 出错时自动换模式或换模型。

### 6.4 三种内部行动

| kind | 含义 | 主要字段 |
| --- | --- | --- |
| `call_tool` | 请求程序执行工具 | tool_name、arguments、reason |
| `request_input` | 向用户索取必要信息 | question、reason |
| `finish` | 提交最终回答接受审核 | answer、reason |

原生接口中 finish 和 request_input 也以“工具定义”的形式提供给模型，但内部会转换为控制流行动，由 Handler 处理，不是 Workspace 文件工具。

非法 JSON、字段不合契约等部分协议错误会转换为内部 `__protocol_error__` 反馈，让模型在预算内修正。缺失有效 call ID、没有有效内容等错误也可能直接结束运行。程序不会对所有供应商异常都无限尝试修复。

<a id="state"></a>
## 7. 领域对象与状态机

实现入口：[domain](../src/kernellens/domain/__init__.py)、[状态定义](../src/kernellens/domain/state.py)。

### 7.1 主要数据对象

| 对象 | 保存内容 | 为什么单独建模 |
| --- | --- | --- |
| TaskRequest | task_type、goal | 将用户请求与运行过程分开 |
| TaskState | request、status、verification | 表示某个时刻的状态快照 |
| AgentAction | 三种明确行动之一 | 限定程序可以接受的控制输入 |
| ToolObservation | 原行动、执行状态、内容及可选验证状态 | 表示工具实际返回的反馈 |
| DecisionBudget | 上限与已用次数 | 让额度校验与消费可测试 |
| StepRecord | 序号、步骤后状态、行动、反馈或错误 | 保存单步事实 |
| RunResult | 最终状态、预算和步骤序列 | 组织一次有限运行的结果 |
| TurnResult | CLI 所需 ID、回答、报告、usage、产物 | 给终端与脚本使用的应用层结果 |

这些对象大多使用 `dataclass(frozen=True)`，状态转换通过创建新对象完成，避免后续更新覆盖早期记录。`frozen` 约束字段赋值，不自动深度冻结所有嵌套内容；CallToolAction 还对参数字典复制并包装成只读映射。

### 7.2 领域生命周期

```text
PENDING ──→ RUNNING ──→ COMPLETED / FAILED / BUDGET_EXHAUSTED
   │            │
   │            ├──→ WAITING_INPUT ──→ RUNNING / FAILED / CANCELLED
   │            └──→ CANCELLED
   └──→ CANCELLED
```

终态没有合法的后续转换。`run_agent()` 只接受 PENDING 和未使用预算，表示一次新的执行。

这里有一个容易误解的实现细节：**领域枚举有 CANCELLED，没有 INTERRUPTED**；正式 CLI 捕获 Ctrl+C 后，在应用输出和数据库中使用字符串 `interrupted`。当前没有 `/cancel` 命令，也没有把 interrupted 作为新的领域枚举值统一进去。

### 7.3 执行状态与验证状态

一次 `check_python` 成功读取并解析检查结果，即使结果是 `syntax=failed`，工具本身也可以是 `succeeded`。这说明检查完成了，不说明被检查的代码合格。

验证字段包括 syntax、api_evidence、compilation、correctness、performance，各自可为 not_run、passed、failed、inconclusive。

正式应用主要把文件检查保存在 Registry 的 checks 和工具反馈中，再生成报告；现有 Runtime 不会把这些结果自动合并为 TaskState.verification 的全部字段。理解真实检查状态应查看对应版本的工具记录和报告，不能只看领域状态对象。

<a id="tools"></a>
## 8. 工具系统与输入契约

实现入口：[arguments.py](../src/kernellens/tools/arguments.py)、[registry.py](../src/kernellens/tools/registry.py)、[workspace.py](../src/kernellens/tools/workspace.py)。

### 8.1 通用工具与知识工具

| 工具 | 主要输入 | 返回内容与作用 |
| --- | --- | --- |
| list_files | path、pattern、limit | 工作区文件列表，支持文件名/路径通配符 |
| read_file | path、start_line、max_lines | 带行号的 UTF-8 片段、总行数、完整文件哈希 |
| search_text | query、path、pattern、limit | 大小写折叠后的字面子串匹配、位置与哈希 |
| write_file | path、content、expected_sha256 | 保存文件，返回新哈希、字节数及备份路径 |
| check_python | path | AST 语法、imports、可选 GEMM 声明检查 |
| read_report | path | 原始 JSON 报告、来源标记及候选哈希是否匹配 |
| compare_reports | baseline_path、candidate_path | 是否可比、拒绝理由、可比时的中位数比值 |
| search_knowledge（默认随包） | query、index、top_k、max_chars、target、include_source | 按问题类型检索，返回有限摘要/短单元全文、来源和 K 编号 |
| read_knowledge（默认随包） | unit_id、start_line、max_chars | 分页阅读语义单元，附依赖与继续位置 |

模型不能通过随便编造工具名获得额外能力。Registry 维护允许调用的名称，未知名称返回失败。

### 8.2 参数为什么用 Pydantic

一个参数类同时服务于两个位置：

1. `model_json_schema()` 生成工具参数说明，告诉模型应该传什么。
2. `model_validate()` 校验实际调用，防止模型返回不合规的数据。

配置使用 strict、extra=forbid、frozen。strict 避免把错误类型悄悄转换为合法类型；extra=forbid 拒绝未声明字段。例如 `{"path": true}` 不会被当作字符串路径使用。

外层 Action 解析还有一道约束：当前工具 arguments 的值只允许有限 JSON 标量，不能直接传嵌套对象或数组。要保存一个 JSON 文件，可以将其内容作为 write_file 的字符串传入。

Schema 只确认“数据形状合法”。path 是字符串之后，是否能访问这个路径，仍由 Workspace 单独判断。

### 8.3 一次工具调用经过哪些步骤

```text
工具名称检查
  → 参数模型验证
  → 实际执行
  → 更新本轮证据、产物或检查索引
  → 结果脱敏与长度限制
  → ToolObservation
```

输入错误、工作区异常、部分文件与文本错误会转成结构化失败反馈。这样模型可以根据 `invalid_arguments`、文件不存在或哈希冲突等原因修改下一次行动。

### 8.4 输出与扫描限制

| 项目 | 当前限制 |
| --- | --- |
| 文件读取 | 最多 1000000 字节，只读普通文件 |
| read_file | 默认 200 行，参数最多 500 行；正文最多 16000 字符 |
| list_files | 默认 100 项，参数最多 200 项 |
| 目录遍历 | 目录与文件扫描计数上限 10000 |
| search_text | 最多扫描 300 个匹配遍历条件的文件；单条文本最多 500 字符 |
| write_file | Schema 内容最多 100000 字符；编码后最多 200000 字节 |
| Registry 反馈 | 超过 22000 字符时改为带 preview 的截断结果 |

输出通常带 truncated 或 scan_limit 信息。尤其要注意，底层遍历达到 10000 上限时不会额外精确反馈所有遗漏情况；“列表较短”或 `truncated=false` 不足以证明巨大目录已经完整查完。

<a id="workspace"></a>
## 9. 工作区隔离与文件写入

### 9.1 路径边界

Workspace 将用户选择的根目录规范化，工具路径可以是相对路径，也可以是落在根目录内的绝对路径。读取前同时检查路径组件、符号链接和规范化后的范围，避免 `../` 越界等情况。

工具排除 `.env*`、`.git`、虚拟环境、依赖目录、`.kernellens`、常见凭证目录与 `.pem/.key` 等敏感文件类型；不跟随工具访问路径中的符号链接。

读取时使用普通文件检查、大小限制，以及平台可用的 O_NOFOLLOW/O_NONBLOCK 标志。FIFO、二进制内容和超大文件会被拒绝，避免把一次读取变成不受控阻塞。

### 9.2 为什么覆盖文件需要 SHA-256

哈希可以视作内容指纹。同一路径的文件被修改后，路径没变，指纹会变。

```text
read_file 得到内容与哈希 H1
  → 用户或其他程序修改文件，当前哈希变为 H2
  → 模型带 H1 请求覆盖
  → 程序发现 H1 ≠ H2，拒绝覆盖，要求重新读取
```

这是一种乐观并发控制：允许先读取再处理，但真正写入时检查版本是否仍符合预期。

### 9.3 写入过程

对已有文件，程序先读取当前版本并比对 expected_sha256，将旧内容备份到本轮内部目录，然后把新内容写入同目录临时文件，flush/fsync 后再次核对当前内容，最后使用 `os.replace` 替换。

对新文件，程序使用硬链接放置临时文件的内容。如果目标在中途被其他操作创建，链接会失败，避免把它直接覆盖。临时文件在收尾阶段清理。

备份路径形如：

```text
.kernellens/runs/<run_id>/backups/<旧内容SHA-256>.bak
```

这能减少普通协作中的覆盖冲突，不是抵御恶意本机并发进程的完整文件系统事务或操作系统沙箱。哈希也不认证内容是谁生成的。

<a id="gemm"></a>
## 10. GEMM 静态声明检查

实现入口：[constraints.py](../src/kernellens/constraints.py)。

### 10.1 为什么 AST 语法检查还不够

Python 代码语法正确，只能说明它符合 Python 的语法规则。例如用户要求 C float16，但代码声明 C float32，依然可能成功解析为 AST。

本项目早期真实模型样本出现过这种偏差，因此增加了 GEMM 声明比较，把“写出了文件”与“可识别的 shape/dtype 符合要求”分开检查。

### 10.2 检查的三个阶段

| 函数 | 输入 | 工作 |
| --- | --- | --- |
| explicit_gemm_constraints | 用户目标文本 | 用有限正则识别明确维度和 dtype |
| declared_gemm_signature | Python 源码 | 从 AST 中读取可解析的维度与类型声明 |
| check_gemm_constraints | 源码与期望字典 | 比较已声明值，列出不一致和未知项 |

目前文本形式包括 `M=N=K=128`、分别指定 M/N/K、`A/B/C float16`、`A/B float16`、`C float16`、`累加 float32` 等。只有目标含 GEMM 或矩阵乘相关标记时才提取；它不能理解所有自然语言表达。

期望字典示意：

```json
{
  "M": 128,
  "N": 128,
  "K": 128,
  "A": "float16",
  "B": "float16",
  "C": "float16",
  "accum": "float32"
}
```

源码分析不执行 Python，只识别有限的常量、赋值、函数默认值和 A/B/C 的 Tensor/Buffer 等调用声明，再从 alloc_fragment 读取可识别的累加类型。形状按 A→MK、B→KN、C→MN 对齐。

### 10.3 三种结果

| 结果 | 含义 |
| --- | --- |
| passed | 提取出的期望项均有一致的静态声明 |
| failed | 至少一个已识别声明与期望冲突 |
| inconclusive | 没有已识别冲突，但存在无法解析的期望项 |

例如 C 的实际声明是 float32、期望是 float16，会返回 mismatch；C 的类型由动态函数决定，分析器可能无法判定，此时不能默认通过。

分析器会保守处理一部分不同作用域或重复赋值造成的冲突，但它不是完整的 Python 解释器、控制流分析器或类型系统。复杂表达式、别名、注解形式和动态构造都可能超出识别能力。

### 10.4 优化如何继承 baseline 契约

优化模式下，Registry 首次读取到具有可识别 A/B/C 声明的 Python 文件时，会提取 baseline_contract，并与用户显式约束合并；同名项以显式约束为准。之后候选检查使用这个契约。

这可以发现常见的 dtype 或维度漂移，但不会验证矩阵乘法数学语义、布局、线程映射、API 可用性、编译或者性能。识别依赖读取顺序，也不等于有一个完整的 baseline 语义分析器。

<a id="review"></a>
## 11. 交付审核与证据机制

实现入口：[review.py](../src/kernellens/review.py)。

### 11.1 证据编号

工具成功执行后，Registry 给返回结果分配 E1、E2 等本轮编号，并记录工具名以及可用的路径和 SHA-256。失败工具反馈会保留在步骤轨迹中，但不分配新的成功证据编号。

回答示意：

```text
候选已保存 [E2]，当前版本的 Python 语法检查通过 [E3]。
GPU 编译、数值正确性和性能尚未运行。
```

这些编号让用户能从结论回到工具观察。它们在每一轮重新计数；历史 E1 不自动变成本轮 E1 的证据。

### 11.2 finish 的程序门槛

1. 回答中出现的 E 编号必须属于本轮证据集合。
2. 本轮使用过成功工具时，答案至少引用一个本轮编号。
3. 生成与优化必须通过 write_file 保存至少一个 Python 产物。
4. 所有本轮 Python 产物都需要针对当前哈希通过 check_python。
5. 存在 GEMM 约束时，至少一个候选通过当前契约；可识别为 GEMM 的产物不能携带未通过的声明。
6. 辅助 Python 脚本也需语法检查，但不要求自身声明 GEMM。
7. 优化还需有读取 Python baseline 的证据，且其哈希与候选集合不同。

审核失败会抛出 FinishRejected。正式应用把原因发给模型，模型可以重新读文件、修改候选、运行检查或补充引用；每次修正都继续消耗预算。

### 11.3 程序保证到哪里

审核器实际检查文件、版本、有限声明与引用编号。Prompt 另外要求模型提供实现依据、实验说明和不确定性说明，但这些自然语言要求没有全部变成自动审核规则。

例如：有 E1 不等于引用真的支持某句话；解释中存在无依据的硬件参数、错误统计术语或者不合理假设，仍可能穿过当前审核。这是模型语义质量的局限，不能用 completed 掩盖。

<a id="context"></a>
## 12. Prompt、上下文与检索

### 12.1 Prompt 的组成

[prompts.py](../src/kernellens/prompts.py) 提供固定行为要求：单次一个工具、先查材料、代码需要保存和检查、优化保留计算契约、区分执行与验证、引用本轮证据等。

每轮还附加任务类型、工作区根目录和从目标提取的 GEMM 约束。近期会话被标为历史材料；读过的源码和日志被视为数据，不应成为新的权限指令。

Prompt 是给模型的行为要求。程序仍通过工具列表、输入校验、路径限制和交付审核独立执行可确定的规则。

### 12.2 上下文如何组织

发送给模型的内容大致分为：

```text
系统规则与工具说明
历史会话片段
本轮目标
本轮 assistant 行动 + 对应 tool 反馈
程序的审核拒绝或纠正反馈
```

Store 默认读取最近 20 条对话消息，适配器进一步只使用其中最后 12 条，并对序列化历史保留最多约 10000 字符。较长历史可能被字符截断；不会把全部历史无上限发给模型。

### 12.3 为什么按组裁剪

原生调用中的 assistant tool_call 与 tool 结果要保持配对。如果只删除调用、保留结果，接口可能无法关联；只保留调用没有结果，也会让对话不完整。

因此 `_messages()` 以“行动与反馈组”为单位移出较早内容，并预留工具 Schema 和提示语的空间。被移出的是本次发送窗口，数据库中的记录仍保留；模型需要旧内容时可重新读取文件。

默认 context_chars 为 48000，这是字符预算，不是模型 tokenizer 计算的精确 Token 数。若系统规则与当前目标本身已经太大，程序返回 ResourceLimit。

### 12.4 当前检索与记忆的形态

通用文件检索仍使用 list_files、read_file、search_text，其中 search_text 是字面子串检索。

当前新增了独立的 TileLang 结构化 RAG：从本地源码按 API、概念、kernel 构造函数和编译器组件抽取知识，建立 API / Concept / Example / Compiler / Operator 五类 FTS5 索引。CLI 默认加载随项目分发的知识快照，应用为相关任务自动预检索；模型可以调用 search_knowledge 查询、read_knowledge 分页阅读。来源带版本、文件哈希和行范围，手动搜索默认 Top-K=5、10000 字符；自动预检索 Top-K=3、最多 7000 字符，预算允许时附短单元全文。

生成/优化在已配置知识库时，需要获得一个相关示例和 API 的完整源码；`source_complete=true` 的预检索可计入，其余用阅读工具补全。check_python 另做有限的公开导出、关键字和 GEMM 局部累加器初始化检查。没有 embedding 或向量库，不妨碍检索增强；也不能把词法召回、API 关键字检查当成完整语义验证。快照包含完整知识正文，普通用户无需 clone TileLang；源码模式留给维护者使用。具体结构、方法、命令与源码入口见 [TileLang RAG 说明](tilelang-rag.md)。

记忆分三处：当前上下文用于本轮推理，SQLite 保存会话与步骤，工作区文件保存代码及用户材料。没有自动提炼长期知识、跨项目共享案例或自动晋升假设为事实的机制。

<a id="storage"></a>
## 13. 会话、运行记录与持久化

实现入口：[storage.py](../src/kernellens/storage.py)。

### 13.1 Workspace、Session、Run、Step 的关系

```text
Workspace
  ├── Session A
  │     ├── Run 1
  │     │     ├── Step 1
  │     │     └── Step 2 ...
  │     └── Run 2 ...
  └── Session B ...
```

- Workspace 决定文件范围和数据库位置。
- Session 是一段可继续的会话。
- Run 是一次用户输入触发的有限执行。
- Step 是一次已经记录的决策与处理结果。

一个会话可以有成功、失败和等待输入的多个运行。恢复会话不会删除以前的失败记录。

### 13.2 SQLite 表

| 表 | 主要内容 |
| --- | --- |
| sessions | 会话 ID、创建时间、标题 |
| messages | 会话关联、角色、对话正文、序号 |
| runs | 任务目标、类型、开始/结束时间、状态、摘要、usage、进程 ID |
| steps | run_id、决策序号、序列化行动/反馈/错误 |

SQLite 不需要额外启动数据库服务。程序启用外键和 WAL，每条消息、每步记录、最终状态分别通过事务提交。

当前 run 保存的是总体时间和 usage；没有完整的逐步骤耗时/用量、每次 HTTP 尝试详情、模型与 Prompt/Schema 版本快照。不能把已有轨迹描述为覆盖所有复现元数据的监控系统。

### 13.3 磁盘产物

```text
<workspace>/
├── artifacts/                       # 建议的候选和说明目录
└── .kernellens/
    ├── history.sqlite3
    ├── history.sqlite3-wal           # SQLite 可能创建的辅助文件
    ├── history.sqlite3-shm
    └── runs/<run_id>/
        ├── report.md
        ├── result.json
        └── backups/<sha256>.bak      # 覆盖文件时产生
```

report.md 保存用户可读结果和程序附加摘要；result.json 保存状态、usage、证据和产物清单；更完整的逐步反馈从 SQLite steps 或 `/trace` 查询。

`artifacts/` 是提示词中的推荐位置，不是唯一允许写入的业务目录。文件仍必须通过工作区限制。`.kernellens/` 属于应用内部存储，不向普通模型文件工具开放；CLI 命令可通过 Store 查询它。

数据库事务和文件落盘不是一个跨系统原子事务。磁盘写入或最终保存失败时，可能留下部分文件或尚未完成的运行记录；CLI 需要报告错误，用户不能仅凭某个文件存在认定记录完整。

<a id="recovery"></a>
## 14. 补充输入、恢复与中断

### 14.1 请求补充信息

模型提出 request_input 后，本轮进入 waiting_input，问题显示给用户。下一次普通输入会被视为补充，应用保留原任务类型，把原目标和本次回答组合成新目标，并创建新的 run。

```text
Run 1：生成需求 → 缺少设备 → waiting_input
用户：NVIDIA A100
Run 2：原目标 + 设备补充 → 重新读取相关材料 → 继续处理
```

若此时输入显式 `/generate`、`/optimize` 或 `/diagnose`，会明确发起对应任务，而不是自动沿用等待中的类型。

### 14.2 失败后显式继续

上一轮为 failed、interrupted 或 budget_exhausted 时，普通输入“继续”“继续处理”“重试”“continue”“retry”会触发继续逻辑。它会携带原目标和历史，但使用新的决策预算。

恢复后的模型需要根据当前文件重新决定行动，没有重放旧的工具调用队列。因此已经保存的代码不会仅因恢复而再次自动覆盖。

### 14.3 Ctrl+C 与进程退出

- 在普通输入提示符按 Ctrl+C：取消当前输入，继续交互。
- 在 Agent 执行过程中按 Ctrl+C：应用尽力保存中断状态、已完成步骤和产物。
- Ctrl+D 或 `/exit`：退出并关闭数据库。
- 强制终止后重新打开工作区：Store 对 running 记录检查原进程是否存在；确认不存在时标记 interrupted。

进程检查使用 PID，并不是完整的跨重启租约系统。中断时正在进行的模型请求或文件操作也不具备事务回滚保证；恢复是新一轮推理，不是恢复解释器到被中断的那条语句。

<a id="errors"></a>
## 15. 预算、超时与错误处理

### 15.1 多种预算约束不同资源

| 配置 | 默认值 | 约束对象 |
| --- | ---: | --- |
| max_decisions | 20 | 一轮决策尝试数 |
| timeout | 60 秒 | HTTP 阻塞操作等待 |
| max_run_seconds | 300 秒 | 请求边界处检查的运行期限 |
| max_output_tokens | 4096 | 请求中的最大输出 Token |
| max_total_tokens | 60000 | 已知累计用量加下一次输出预留的门槛 |
| context_chars | 48000 | 发送消息及 Schema 的字符规模 |
| max_retries | 2 | 一个 HTTP 请求最多额外重试次数 |

配置文件或环境变量使用 `KERNELLENS_` 加大写名称，例如 `KERNELLENS_MAX_DECISIONS`。CLI 提供 `--max-steps`、`--timeout` 等常用覆盖项，完整说明见 [CLI 手册](cli.md)。

一次决策可能因为 HTTP 重试产生多个请求；一次成功工具执行也不等于一次最终完成。决策次数、请求次数、Token 用量和费用是不同指标。

### 15.2 为什么在请求前消费决策额度

无效行动、模型异常、工具失败和审核拒绝都已经消耗了实际工作。因此 Runtime 在尝试决策之前先消费额度，不会因失败而退回。这让持续出错的循环也能在有限步数内停止。

达到决策上限时状态为 budget_exhausted。Token 或时间门槛由客户端抛出 ResourceLimit，当前 Runtime 将其记录为 failed，并保留具体原因；并非所有“预算相关错误”都使用同一个状态字符串。

### 15.3 HTTP 错误策略

| 情况 | 当前处理 |
| --- | --- |
| 400 | 报告请求不兼容，提示核对模型与工具模式 |
| 401 / 403 | 报告认证或访问权限问题，不自动重试 |
| 402 | 报告额度/付费不可用，不自动重试 |
| 404 | 报告接口或模型不存在 |
| 429、500、502、503、504 | 在重试和剩余时间内有限退避 |
| 网络、连接和超时错误 | 有限重试，失败后给出明确连接错误 |
| 非 JSON、超大响应、缺少 message | 拒绝响应并记录错误 |
| finish_reason=length | 报告模型输出被截断 |
| API 重定向 | 拒绝，要求配置最终 endpoint |

退避从 1 秒、2 秒逐步增长，单次最多 4 秒，同时受剩余时间限制。网络 timeout 会按运行剩余时间缩小。该实现不是操作系统级的全进程硬截止时间。

### 15.4 用量与费用为什么有 unknown

客户端只累积供应商提供的非负整数 prompt_tokens 与 completion_tokens。如果某次失败、中断或响应没有完整 usage，total_tokens 设为 null，usage_complete 为 false；已知计数仍可保留，不能据此当作完整账单。

max_total_tokens 不精确预估下一次输入 Token，也无法控制供应商在失败请求上的计费；因此它是准入门槛，不是费用硬上限。当前 cost 为 null，没有集成价格计算。

### 15.5 退出码

| 返回码 | 含义 |
| --- | --- |
| 0 | 单次任务 completed 或正常退出 |
| 1 | 配置/执行错误、决策预算耗尽等 |
| 2 | 单次任务等待用户输入；argparse 参数错误也使用 2 |
| 130 | 单次执行或外层流程被 Ctrl+C 取消 |

<a id="reports"></a>
## 16. 服务器报告与性能比较

报告模板：[verification-report.example.json](../examples/verification-report.example.json)。它只提供字段形状，没有伪造的测量数据。

### 16.1 报告应包含什么

| 字段 | 用途 |
| --- | --- |
| candidate_path | 实际被测试的候选路径，相对工作区 |
| candidate_sha256 | 实际被测试代码的内容标识 |
| environment | 设备、TileLang revision、CUDA 等环境记录 |
| workload | shape、dtype、布局等输入条件 |
| measurement | 计时方法、预热、每样本迭代数等 |
| checks | 编译和数值检查结果 |
| latency_ms | 多个真实延迟样本 |

`read_report` 要求顶层是 JSON 对象，返回原报告并尝试关联代码哈希；它不是对所有报告字段做严格业务 Schema 校验。如果字段不齐或哈希不匹配，candidate_matches 可以为 false，而“读取工具执行成功”依然成立。

### 16.2 compare_reports 的比较条件

只有同时满足以下条件，工具才计算比值：

1. 两份报告的代码哈希都匹配当前文件。
2. environment、workload、measurement 都是非空字典，并且两边完全相等。
3. 两份 checks 都明确写着 correctness=passed。
4. 两组 latency_ms 都至少包含三个正的有限数值，不接受 bool、NaN 或无穷值。

字段不一致时返回 comparable=false 和 reasons，不给出中位数比值。

条件满足时：

```text
baseline_median_ms  = median(baseline.latency_ms)
candidate_median_ms = median(candidate.latency_ms)
median_ratio       = baseline_median_ms / candidate_median_ms
```

大于 1 表示用户提供的这些样本中候选中位数更低，小于 1 表示更高。它是描述性比较，不证明统计显著性或换个 workload 仍有同样收益。

当前校验主要检查字段存在、相等和数据形状，没有认证报告提供者，也不会证明 environment 字典已经完整覆盖所有干扰变量。来源始终保留为 user_report，不宣称 Agent 在本机测出了该结果。

<a id="examples"></a>
## 17. 三个任务示例与真实观察

以下命令展示使用方式；实际工具顺序由模型根据反馈决定，不是固定流水线。

### 17.1 生成候选

```text
/generate 生成基础 GEMM：M=N=K=128，A/B/C float16，累加 float32，行主序，目标 A100。保存候选和服务器验证说明，注明没有核对的 API。
```

典型过程是调查工作区、确认参数、生成文件、运行静态检查、解释检查边界、提交引用证据的回答。模型缺少必要信息时也可能先 request_input。

如果输出 dtype 错误，静态声明检查会提供 mismatch；模型修正文件后，旧哈希对应的检查失效，需要重新 check_python。

### 17.2 优化已有候选

```text
/optimize 读取 artifacts/gemm.py，保持计算契约，提出一项参数改动，另存候选，并说明如何与 baseline 对照。
```

本轮会读取已有代码，形成优化假设，保存新文件，并对可识别的声明做比较。假设可以被实验否定；只有提出一个优化参数，不等于已经找到更快的实现。

### 17.3 诊断问题

```text
/diagnose 读取 bug.py，解释 mean([]) 为什么会报错，将解释保存为 artifacts/diagnosis.md。
```

对 `sum(values) / len(values)` 而言，空列表使分母为零。模型可以结合读取证据解释这一点，并建议按业务需要拒绝空输入或定义明确返回值。程序没有执行这段用户代码，这属于基于源码的诊断。

### 17.4 已发生的 MiMo 验收

| 任务 | 真实请求数 | 供应商报告 Token | 已观察到的结果 |
| --- | ---: | ---: | --- |
| diagnose | 3 | 10471 | 读文件、保存诊断、引用证据并完成 |
| generate | 8 | 57952 | 保存候选与说明，GEMM 声明通过 |
| optimize | 7 | 43968 | 读取 baseline、另存候选，声明保持一致 |

这些是本项目特定验收的记录，不是平均速度、任务成功率或费用基准。验收脚本使用了 12 次决策、90 秒请求 timeout、480 秒运行期限和 6000 输出 Token 的显式配置，与 CLI 默认值不同。

真实过程还出现过两类修正：生成时多工具提议被整体拒绝后改为顺序执行；优化首次 finish 未引用本轮证据，被拒绝后补充引用。它们说明反馈循环实际发挥了作用。

生成内容的人工审阅也发现了错误：验证说明将平均耗时称为中位数、对照计时方式不一致；优化报告含无依据的预测百分比和错误年份。因此三条流程 completed 只证明工具和记录闭环，不能直接把候选或说明交给服务器当作已审核的测试方案。

完整 run ID、历史失败和边界见 [验收记录](validation.md)。

<a id="engineering"></a>
## 18. 技术选型与工程方法

### 18.1 为什么采用模块化单进程

目前一名用户在一个终端里操作工作区。把模型适配、工具、审核和存储分成模块，已经能隔离职责，暂不需要消息队列或独立服务之间的协调。

对学习者而言，这种结构还能让一次输入的调用链保持可追踪：从 CLI 到应用、Runtime，再到工具和模型，最后回到报告。

### 18.2 数据与校验的选择

| 选择 | 对当前需求的作用 |
| --- | --- |
| dataclass / StrEnum | 明确领域对象和有限状态，保留 Python 直接可读性 |
| Pydantic | 将工具说明和实际输入校验建立在同一参数模型上 |
| argparse | 实现标准命令行参数、帮助和返回码 |
| urllib | 满足当前 HTTP 请求、timeout 和错误处理，不额外引入 SDK 重试层 |
| SQLite | 本地事务与重启后查询，不要求部署数据库服务 |
| AST | 检查代码声明和语法时不执行用户代码 |
| SHA-256 | 关联文件版本、检查记录、覆盖前状态和报告 |
| uv / src 布局 | 锁定依赖并明确安装包与源码的关系 |

### 18.3 可调用对象与依赖注入

DecisionAdapter、ToolRegistry 和 ReportReviewer 都可以通过 `__call__` 像函数一样调用。Runtime 接收的是所需接口，不在内部创建这些具体对象。

这让测试可以提供预设模型回复、故意失败的执行器或不同审核结果，观察状态变化，而不消耗真实 API。测试不是“模型肯定会这样回答”的证明，而是“出现这类反馈时程序如何处理”的证据。

### 18.4 测试覆盖如何分层

- 领域与 Runtime 单元测试：状态转换、字段不变量、预算、Handler 和记录关系。
- 配置与文件测试：优先级、参数错误、路径越界、符号链接、文件冲突、报告关联。
- 协议集成测试：用可控制 transport 模拟工具调用、非法回复、HTTP 错误和中断。
- CLI 集成测试：真实启动子进程，通过 localhost HTTP fixture 完成交互。
- 显式真实验收：使用云端模型，保留三条工作流的产物和记录。
- 人工与硬件验证：判断专业语义、核对 API、执行对应 GPU 实验。

CLI 初版记录中的 371 个测试通过，证明当时覆盖到的程序行为。RAG 实现后增加了检索与声明解析检查，并重新进行了真实模型调用；结果见 [RAG 验证记录](rag-validation.md)。这些证据不能保证所有未来模型输出正确。

<a id="limits"></a>
## 19. 已验证结果、局限与后续方向

### 19.1 已有工程证据

CLI 初版验收记录包括：371 个自动测试通过，Ruff 检查通过，源码包和 wheel 构建及安装入口验证通过，工作区选择的真实终端验证通过，MiMo 三条真实工具流程完成。后续 RAG 的新增检查以 [当前状态](status.md) 和 [RAG 说明](tilelang-rag.md) 为准，不将旧算子结果追溯标为已核对 API。

原项目虚拟环境曾指向复制前的相邻仓库，后来通过重新安装核对了当前导入位置。这说明“测试绿了”还应确认测试运行的究竟是哪份代码。`--doctor` 可以辅助排查此类问题。

### 19.2 当前限制

| 限制 | 对使用的影响 |
| --- | --- |
| RAG 存在动态导出、外部依赖与 C++ 结构扫描覆盖边界 | 缺少定义或来源过期时需要补证据，不能仅凭检索成功认定 API 正确 |
| 不自动执行用户代码或 GPU | 编译、正确性和性能需要服务器完成 |
| 审核只覆盖确定性门槛 | 自然语言解释与实验说明仍可能错误 |
| 自然语言任务分类与约束提取有限 | 对复杂需求应显式指定任务类型并核对提取结果 |
| 文本检索与上下文有上限 | 需要分段查阅，不能假设一次看全大型仓库 |
| 恢复创建新 run | 没有精确恢复 HTTP 请求或文件操作的中间状态 |
| 费用和观测数据不完整 | cost 未知，部分失败 usage 缺失，没有完整逐步性能追踪 |
| 文件边界与脱敏不是万能防护 | 未识别的敏感内容、恶意本机并发仍需要额外控制 |

脱敏会替换当前已知密钥，并处理部分 `sk-` 和 Bearer 模式；它不是通用的数据分类或秘密发现系统。允许读取的源码和文本片段可能进入云端模型上下文，工作区内容应由用户根据实际任务选择。

### 19.3 后续可以怎样演进

以下是基于当前边界的方向，不代表已经实现：

1. **检索质量持续评估**：已有固定 revision 和可核查来源，继续扩充真实问题评估，检查动态导出、复杂依赖和目标适配的漏召回。
2. **语义质量评测**：建立经审核的生成、优化和诊断案例，区分程序流程通过与专业内容通过。
3. **报告质量约束**：统一测试方法、容差、计时口径与来源，减少无依据量化描述。
4. **复现元数据**：在 run 中保存模型、Prompt、Schema 与环境版本及更细的耗时。
5. **经需求确认的执行器**：在隔离环境运行 GPU 编译、正确性和基准；处理执行权限、超时与结果来源。
6. **检索优化与服务化**：有召回或多人使用需求时，再评估索引、重排、Web/API 等组件。

<a id="reading"></a>
## 20. 源码阅读路线与术语表

### 20.1 建议的阅读顺序

| 顺序 | 文件 | 阅读时关注的问题 |
| --- | --- | --- |
| 1 | [cli.py](../src/kernellens/cli.py) | 用户输入怎样变成一次任务，如何选择工作区？ |
| 2 | [application.py](../src/kernellens/application.py) | 一轮任务需要哪些依赖，最终结果如何组成？ |
| 3 | [task.py](../src/kernellens/domain/task.py)、[state.py](../src/kernellens/domain/state.py)、[action.py](../src/kernellens/domain/action.py) | 请求、状态和行动有什么不同？ |
| 4 | [loop.py](../src/kernellens/runtime/loop.py)、[handlers.py](../src/kernellens/runtime/handlers.py) | 哪些分支继续，哪些分支停止？ |
| 5 | [client.py](../src/kernellens/models/client.py) | HTTP 回复如何变成 Action，反馈如何回到模型？ |
| 6 | [arguments.py](../src/kernellens/tools/arguments.py)、[registry.py](../src/kernellens/tools/registry.py) | 参数校验和执行授权分别在哪里？ |
| 7 | [workspace.py](../src/kernellens/tools/workspace.py) | 文件读写和报告比较的边界是什么？ |
| 8 | [constraints.py](../src/kernellens/constraints.py)、[review.py](../src/kernellens/review.py) | “可以提交”具体由哪些程序条件决定？ |
| 9 | [storage.py](../src/kernellens/storage.py) | 哪些信息持久化，怎样恢复会话？ |
| 10 | [test_live_protocol.py](../tests/test_live_protocol.py)、[test_cli.py](../tests/test_cli.py) | 如何用可控制的输入证明这些边界？ |

### 20.2 术语表

| 术语 | 本项目中的意思 |
| --- | --- |
| Agent Loop | 模型行动、程序执行和反馈构成的有限循环 |
| Runtime | 执行行动并控制状态、预算和停止的代码 |
| Action | 模型提出的结构化操作请求 |
| Observation | 工具已经执行后得到的反馈 |
| Schema | 参数字段、类型与范围的说明 |
| Guardrail | 由输入、路径、预算和审核等规则形成的运行限制 |
| AST | 源代码的语法树，用于静态查看结构 |
| Contract | 本轮需要保持的可检查约束，如 shape/dtype |
| Evidence | 可追溯的工具观察及编号、路径、哈希 |
| Baseline | 对比所用的原始实现或原始测量 |
| Artifact | 保存下来的候选、说明、报告等文件 |
| Session | 能够包含多轮任务的会话 |
| Run | 一次有限执行，有独立 ID、预算和终态 |
| Checkpoint | 保存状态或记录，以便检查和继续；当前恢复是新 run |
| Dependency Injection | 将模型、工具和审核依赖传入 Runtime |
| Optimistic Concurrency | 写入前比对读取时的版本，冲突时重新读取 |

进一步阅读：[CLI 手册](cli.md)、[架构决策](decisions/002-cli-agent.md)、[实际验收记录](validation.md)、[当前项目状态](status.md)。
