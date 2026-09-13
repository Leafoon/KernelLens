# RUN-003H：组装有限 Agent Loop

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前处于 Phase 2 — State & Minimal Runtime。RUN-003G 已提交为
`8b7ccf5 feat: add validated runtime results`，进入本单元前工作区干净。
进入本单元前，完整验收为 304 个测试及 lint/format、运行结果观察通过。

已有模块分别处理一次决策、额度、三种行动、步骤记录和运行结果。
本单元只增加一个协调函数 run_agent，把这些模块接成可以自动推进和停止的内存运行流程。
模型、执行器和审核器先用本地替身；业务算子能力仍在后续工具与模型阶段接入。

## Concept

**Agent Loop 的核心是反馈改变下一步选择。** 模型读状态与反馈，提出一个行动；
程序处理行动，把工具反馈交回下一轮，直到状态不再允许运行。
本版逐步选择行动，没有独立 Planner 类，也不需要先生成一份完整计划。
生成、优化和诊断将共享同一个 Runtime；本单元用“读取报告失败后请求补充”的简单场景观察控制流程。

**循环拥有运行中的最新快照。** TaskState 和 DecisionBudget 都是冻结对象，
所以必须保存 transition_to 和 consume 的返回值。旧步骤仍引用当时的状态。
局部 steps 用 list 方便逐次追加，退出时转为 tuple 交给 RunResult；
observations 始终是 tuple，每次追加得到新元组，旧轮次收到的反馈不会被原地扩充。

**失败反馈与异常采用不同策略。** 这是本单元明确的首版行为：

| 情况 | 行为 | 是否继续决策 |
| --- | --- | --- |
| 工具正常返回 SUCCEEDED / FAILED | 保存反馈与记录，状态仍为 RUNNING | 有额度时继续 |
| RequestInputAction | 保存 WAITING_INPUT 与问题行动 | 停止本次运行 |
| FinishAction 审核接受 | 保存 COMPLETED | 停止 |
| 审核拒绝、模型／解析／执行／审核异常 | 消费的额度保留，保存 FAILED 与错误记录 | 停止，不自动重试 |
| 尚需继续但额度耗尽 | 保存 BUDGET_EXHAUSTED | 停止，不虚构新尝试 |
| 入口不合法 | 抛异常给调用者 | 不消费、不调用依赖 |

前几单元的 Handler 仍负责校验并传播异常。现在由运行边界把一次尝试中的 Exception
转换成可检查的 FAILED 结果；恢复与拒绝原因反馈留到后续单元，不在这里悄悄重试。

## Design

### 输入、输出与职责

`run_agent(state, *, budget, model, executor, reviewer) -> RunResult`。

| 输入 | 约束与用途 |
| --- | --- |
| state | TaskState，必须是 PENDING；保留请求与已有 verification |
| budget | DecisionBudget，used_decisions 必须为 0；上限由调用者明确给出 |
| model | DecisionModel；接收当前 RUNNING 状态和本次运行内已有工具反馈 |
| executor | ToolExecutor；由程序注入，负责处理合法的 CallToolAction |
| reviewer | FinishReviewer；由程序注入，决定是否接受 FinishAction |
| 返回值 | RunResult：停止状态、最新预算、完整 StepRecord tuple |

星号后的参数必须按名称传入，避免把几个 Callable 的位置传错。
入口只允许新运行：没有历史记录参数，所以不能接收旧预算或把 WAITING_INPUT 当作恢复入口。
RunResult 本身能表达取消结果，但本版 run_agent 不提供取消 API；数据契约的表达能力可以大于当前入口支持的行为。

### Control Flow

参见 [有限循环与自动记录图](diagrams/agent-loop.md)，图源可直接在 VS Code Markdown 预览。
每次循环按以下顺序推进：

1. 状态仍为 RUNNING，才尝试 consume；保存新预算后才调用模型。
2. 清空本次 action、observation、error，避免混入上一轮材料。
3. decide_once 复用已有 Parser，不再写一套解析规则。
4. 按行动类型调用已有 Handler；工具反馈追加到下一轮输入。
5. 尝试抛 Exception 时，保存 FAILED 与异常类型／文本；解析前失败允许 action 为 None。
6. 在尝试处理之后统一追加一条 StepRecord，编号使用已消费额度。
7. 循环条件决定是否继续；退出后 RunResult 再检查结果集合的一致性。

预算检查的 try 只包围 consume。因此模型或工具自己抛 DecisionBudgetExhausted，
也属于它们的执行异常，不会被误当成本地预算耗尽。
记录与最终结果的构造放在尝试的 except 范围之外：内部记录不变量被破坏时直接暴露错误，不把程序缺陷伪装成正常结果。

### 边界与组件取舍

一个普通函数即可协调现有接口，不需要新增框架、队列、数据库或 Runtime 类。
只串行执行一个行动，暂不支持并发、断点恢复、持久化、真实审核策略或错误恢复。
本版收集工具反馈但不自动合并 verification；模型也暂不接收完整 StepRecord 历史。

次数上限保证回调正常返回或抛 Exception 时，决策尝试不超过 max_decisions；
它不是墙钟超时，单次回调卡住仍会阻塞，也不限制反馈字节数、Token 或实际 Provider 请求数。
KeyboardInterrupt / SystemExit 属于 BaseException，不被这里的 except Exception 捕获；
这类中断和进程终止没有 RunResult，也没有持久化保证。异常文本当前仅用于本地调试，对外展示和落盘前再引入脱敏。
替身可以证明调用次序与停止策略，不能证明模型会规划、算子正确或真实审核有效。

## Implementation

本单元的两个核心文件由你亲手创建。已有模块不用改动，助手只创建本讲义与专项图、同步项目文档。

### 1. 创建循环入口

文件：`src/kernellens/runtime/loop.py`。共约 80 行，先按下面五个逻辑块理解，再输入。

```python
from kernellens.domain.action import (
    AgentAction,
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.runtime.budget import DecisionBudget, DecisionBudgetExhausted
from kernellens.runtime.handlers import (
    FinishReviewer,
    ToolExecutor,
    apply_call_tool,
    apply_finish,
    apply_request_input,
)
from kernellens.runtime.records import RunResult, StepRecord
from kernellens.runtime.step import DecisionModel, decide_once


def run_agent(
    state: TaskState,
    *,
    budget: DecisionBudget,
    model: DecisionModel,
    executor: ToolExecutor,
    reviewer: FinishReviewer,
) -> RunResult:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(budget, DecisionBudget):
        raise TypeError("budget must be a DecisionBudget")
    if state.status is not TaskStatus.PENDING:
        raise ValueError("state must be pending for a new run")
    if budget.used_decisions != 0:
        raise ValueError("budget must be unused for a new run")
    for name, dependency in (
        ("model", model),
        ("executor", executor),
        ("reviewer", reviewer),
    ):
        if not callable(dependency):
            raise TypeError(f"{name} must be callable")

    state = state.transition_to(TaskStatus.RUNNING)
    observations: tuple[ToolObservation, ...] = ()
    steps: list[StepRecord] = []

    while state.status is TaskStatus.RUNNING:
        try:
            budget = budget.consume()
        except DecisionBudgetExhausted:
            state = state.transition_to(TaskStatus.BUDGET_EXHAUSTED)
            break

        action: AgentAction | None = None
        observation: ToolObservation | None = None
        error: str | None = None
        try:
            action = decide_once(state, model, observations)
            if isinstance(action, RequestInputAction):
                state = apply_request_input(state, action)
            elif isinstance(action, FinishAction):
                state = apply_finish(state, action, reviewer=reviewer)
            elif isinstance(action, CallToolAction):
                observation = apply_call_tool(state, action, executor=executor)
                observations += (observation,)
            else:
                raise TypeError("unsupported agent action")
        except Exception as exc:
            state = state.transition_to(TaskStatus.FAILED)
            error = f"{type(exc).__name__}: {exc}"

        steps.append(
            StepRecord(budget.used_decisions, state, action, observation, error)
        )

    return RunResult(state, budget, tuple(steps))
```

- **入口检查**：尽早拒绝接线错误和不支持的恢复输入；即使第一步未必用到工具或审核，也先检查所有必需依赖。
- **快照初始化**：PENDING 转 RUNNING，反馈与记录仅属于本次调用，没有模块级共享列表。
- **预算门槛**：先消费再尝试；耗尽发生在一次尝试之外，不新建记录。
- **一次尝试**：三种 Handler 保持各自职责。except Exception 把这次失败记录下来，没有隐式重试。
- **统一记录与返回**：每次尝试都走同一个记录位置。完成或等待改变了 state，下一次 while 检查就直接退出，防止最后额度上的完成被覆盖。

这里的 else 是未来扩展防线：如果新增行动却遗漏 Handler 分支，应显式失败，不静默忽略。
action 赋值要等 decide_once 正常返回才发生，因此模型或解析异常时会保留 None。
error 包含异常类型，即使异常消息为空也能留下非空材料。

### 2. 创建循环行为测试

文件：`tests/test_loop.py`。5 个测试函数，参数化后 22 个用例。

```python
import pytest

from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget
from kernellens.runtime.loop import run_agent


def make_state(status=TaskStatus.PENDING):
    return TaskState(TaskRequest(TaskType.DIAGNOSE, "检查报告是否可用"), status)


def tool_payload():
    return {
        "kind": "call_tool",
        "tool_name": "read_report",
        "arguments": {"path": "report.json"},
        "reason": "读取反馈。",
    }


def finish_payload():
    return {"kind": "finish", "answer": "报告已取得。", "reason": "仅确认读取结果。"}


def must_not_run(*args):
    pytest.fail("unexpected dependency call")


@pytest.mark.parametrize("tool_status", list(ToolExecutionStatus))
def test_feedback_drives_next_action_and_stop(tool_status):
    initial = make_state()
    allowance = DecisionBudget(2)
    calls, feedback, reviews = [], [], []

    def model(state, observations):
        calls.append((state, observations))
        if not observations:
            return tool_payload()
        if observations[-1].status is ToolExecutionStatus.FAILED:
            return {
                "kind": "request_input",
                "question": "请提供报告。",
                "reason": "读取失败。",
            }
        return finish_payload()

    def executor(action):
        result = ToolObservation(action, tool_status, "固定测试反馈。")
        feedback.append(result)
        return result

    def reviewer(state, action):
        reviews.append((state, action))
        return True

    result = run_agent(
        initial, budget=allowance, model=model, executor=executor, reviewer=reviewer
    )

    succeeded = tool_status is ToolExecutionStatus.SUCCEEDED
    expected = TaskStatus.COMPLETED if succeeded else TaskStatus.WAITING_INPUT
    assert result.state.status is expected
    assert len(calls) == result.budget.used_decisions == len(result.steps) == 2
    assert [step.decision_number for step in result.steps] == [1, 2]
    assert calls[0][1] == ()
    assert len(feedback) == 1
    assert calls[1][1] == (feedback[0],)
    assert calls[1][1][0] is result.steps[0].observation is feedback[0]
    assert feedback[0].action is result.steps[0].action
    assert result.steps[0].state_after is calls[1][0]
    assert result.steps[0].state_after.status is TaskStatus.RUNNING
    assert result.steps[-1].state_after is result.state
    assert len(reviews) == int(succeeded)
    if succeeded:
        assert reviews[0][1] is result.steps[-1].action
    assert all(step.error is None for step in result.steps)
    assert initial.status is TaskStatus.PENDING
    assert allowance.used_decisions == 0
    assert result.state.request is initial.request
    assert result.state.verification is initial.verification


@pytest.mark.parametrize("limit", [1, 3])
def test_budget_stops_repeated_tools_without_extra_attempt(limit):
    histories = []

    def model(state, observations):
        histories.append(observations)
        return tool_payload()

    def executor(action):
        return ToolObservation(action, ToolExecutionStatus.FAILED, "仍缺报告。")

    result = run_agent(
        make_state(),
        budget=DecisionBudget(limit),
        model=model,
        executor=executor,
        reviewer=must_not_run,
    )

    assert result.state.status is TaskStatus.BUDGET_EXHAUSTED
    assert len(histories) == result.budget.used_decisions == len(result.steps) == limit
    assert [len(history) for history in histories] == list(range(limit))
    assert [step.decision_number for step in result.steps] == list(range(1, limit + 1))
    assert all(step.state_after.status is TaskStatus.RUNNING for step in result.steps)
    for history in histories:
        for index, observation in enumerate(history):
            assert observation is result.steps[index].observation


@pytest.mark.parametrize(
    ("failure", "error_type", "expected_calls"),
    [
        ("model", "RuntimeError", ["model"]),
        ("parser", "ValueError", ["model"]),
        ("executor", "RuntimeError", ["model", "executor"]),
        ("reviewer", "RuntimeError", ["model", "reviewer"]),
        ("rejected", "FinishRejected", ["model", "reviewer"]),
    ],
)
def test_failed_attempt_is_charged_recorded_and_not_retried(
    monkeypatch, failure, error_type, expected_calls
):
    calls = []
    original_consume = DecisionBudget.consume

    def consume(budget):
        calls.append("consume")
        return original_consume(budget)

    monkeypatch.setattr(DecisionBudget, "consume", consume)

    def model(state, observations):
        calls.append("model")
        if failure == "model":
            raise RuntimeError("model unavailable")
        if failure == "parser":
            return {"kind": "unknown"}
        return tool_payload() if failure == "executor" else finish_payload()

    def executor(action):
        calls.append("executor")
        raise RuntimeError("tool unavailable")

    def reviewer(state, action):
        calls.append("reviewer")
        if failure == "reviewer":
            raise RuntimeError("review unavailable")
        return False

    result = run_agent(
        make_state(),
        budget=DecisionBudget(3),
        model=model,
        executor=executor,
        reviewer=reviewer,
    )

    assert result.state.status is TaskStatus.FAILED
    assert calls == ["consume", *expected_calls]
    assert result.budget.used_decisions == len(result.steps) == 1
    record = result.steps[0]
    assert record.decision_number == 1
    assert record.state_after is result.state
    assert (record.action is None) == (failure in {"model", "parser"})
    assert record.observation is None
    assert record.error.startswith(f"{error_type}:")


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        (field, None, TypeError)
        for field in ("state", "budget", "model", "executor", "reviewer")
    ]
    + [
        ("state", make_state(status), ValueError)
        for status in TaskStatus
        if status is not TaskStatus.PENDING
    ]
    + [("budget", DecisionBudget(2, 1), ValueError)],
)
def test_invalid_entry_has_no_attempt(monkeypatch, field, value, error_type):
    monkeypatch.setattr(DecisionBudget, "consume", must_not_run)
    values = {
        "state": make_state(),
        "budget": DecisionBudget(2),
        "model": must_not_run,
        "executor": must_not_run,
        "reviewer": must_not_run,
    }
    values[field] = value
    with pytest.raises(error_type, match=field):
        run_agent(**values)


def test_keyboard_interrupt_is_not_converted_to_a_task_failure():
    def model(state, observations):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_agent(
            make_state(),
            budget=DecisionBudget(1),
            model=model,
            executor=must_not_run,
            reviewer=must_not_run,
        )
```

测试关心调用者能观察到的控制行为，而不重复每个领域类的字段测试：

| 用例组 | 数量 | 验收目标 |
| --- | ---: | --- |
| 反馈驱动下一步 | 2 | 成功后审核完成，失败后请求信息；第二轮拿到原反馈，停止后不再调用；最后额度上仍可完成 |
| 重复工具行动的预算停止 | 2 | 上限 1 / 3，调用与记录无额外一步；历史元组保持各轮快照 |
| 失败尝试 | 5 | 模型、解析、执行、审核异常及审核拒绝；先消费后调用，一条失败记录，无重试 |
| 非法入口 | 12 | 五个非法字段、六种非 PENDING 状态、用过的预算；在消费或依赖调用前拒绝 |
| 用户中断 | 1 | KeyboardInterrupt 原样传播，不转换成 FAILED 结果 |

monkeypatch 在失败测试中临时包装 consume，记录调用先后；在入口测试中把 consume
换成一旦调用就失败的替身。pytest 会在每个用例结束后恢复原方法。
must_not_run 使用 pytest.fail 暴露任何不该发生的调用；测试替身不是生产服务。
本单元不新增共享测试框架，辅助函数只在这个测试文件内使用。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_loop.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

2026-09-10 实际验收：用户实现与测试 Review 通过；全量 **326 passed（0.14s）= 304 + 22**，包含全部新增循环用例。
助手使用 `uv run --locked --offline --no-cache --no-python-downloads pytest -q`；Ruff lint 和格式检查通过（32 个 Python 文件）。
实现与测试 AST 均与讲义一致；助手只整理 loop.py 的参数缩进、空行与末尾换行，写入前确认 AST 和非空白内容均不变。
未修改核心逻辑、测试或已有模块。

## Observe

下面的本地替身示例已运行验证。
这次由真正的 run_agent 创建预算快照和步骤，不再手工组装 StepRecord。

```bash
uv run --locked python - <<'PY'
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget
from kernellens.runtime.loop import run_agent


def model(state, observations):
    print(f"model: state={state.status.value}, feedback={len(observations)}")
    if not observations:
        return {
            "kind": "call_tool",
            "tool_name": "read_report",
            "arguments": {"path": "report.json"},
            "reason": "读取执行反馈。",
        }
    return {
        "kind": "request_input",
        "question": "请提供服务器执行报告。",
        "reason": "当前未取得报告。",
    }


def executor(action):
    print(f"tool: {action.tool_name}")
    return ToolObservation(action, ToolExecutionStatus.FAILED, "报告不存在。")


def reviewer(state, action):
    raise AssertionError("本例不应走到交付审核")


result = run_agent(
    TaskState(TaskRequest(TaskType.DIAGNOSE, "检查报告是否可用")),
    budget=DecisionBudget(3),
    model=model,
    executor=executor,
    reviewer=reviewer,
)
print(f"result: {result.state.status.value}")
print(f"used: {result.budget.used_decisions}/{result.budget.max_decisions}")
for step in result.steps:
    print(step.decision_number, step.action.kind, step.state_after.status.value)
print(f"question: {result.steps[-1].action.question}")
PY
```

2026-09-10 实际输出：

```text
model: state=running, feedback=0
tool: read_report
model: state=running, feedback=1
result: waiting_input
used: 2/3
1 call_tool running
2 request_input waiting_input
question: 请提供服务器执行报告。
```

逐项观察：

- 工具只调用一次；返回 FAILED 后模型获得反馈，选择请求信息。
- 请求信息后仍剩一次额度，但没有第三次模型调用：状态和预算共同决定是否允许继续。
- 两次模型尝试对应两条自动记录，第二条保存了待回答问题。
- 外部模型、文件读取和 GPU 执行都由本地函数替身替代；这里没有真实读取 report.json。

验收额外断言通过：模型 2 次、工具 1 次、审核 0 次；原状态仍为 PENDING、原预算仍未使用；
步骤关联原行动和反馈，最后步骤保存最终状态，原请求与 verification 引用保留。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 第一轮就被拒绝 | pending / unused 报错 | 输入是旧状态或旧预算 | 确认本单元入口仅支持新运行，不绕过检查模拟恢复 |
| 次数超过上限 | 调用数量多于 limit | 没保存 consume 的返回值或在调用后消费 | 检查 budget = budget.consume() 的位置与返回快照 |
| 第二轮没看到反馈 | feedback 仍为 0 | 未追加反馈，或把 observations 在循环内部清空 | 保留整次运行的元组；只重置单步变量 |
| 工具返回 FAILED 就停止 | 第一条记录的状态成了 FAILED | 混淆 ToolExecutionStatus 与 TaskStatus | 正常返回的反馈送入下一轮，抛异常才走失败策略 |
| 审核后仍调用模型 | reviews 后出现更多调用 | 忽略 Handler 返回的新状态 | 检查 state = apply_finish(...) 与 while 条件 |
| 异常没有记录或不扣额度 | 失败用例数量不匹配 | 过早 return，或把消费放在成功路径 | 对照调用顺序与统一 steps.append 位置 |
| 第二轮沿用旧反馈或错误 | StepRecord 校验报错或材料混杂 | 没在每次尝试前重置单步变量 | 检查 action / observation / error 的初始化位置 |

先读失败用例和实际记录，再提出假设、验证并自己修改核心逻辑。
本单元没有超时机制；有意测试卡住的真实服务应留到相应机制就绪后。

## Checkpoint

本单元应学会：逐步决策与反馈闭环、快照所有权、先消费后尝试、统一记录、
异常处理边界，以及状态和预算如何共同终止运行。

run_agent 和 22 个新用例已由你实现并验收；全量 326 个测试、lint/format 和自动循环观察通过。
正常结束、等待、非法行动和预算耗尽已有实际行为与测试，达到 Phase 2 的实现验收要求；仍是使用替身的最小 Runtime。

已核对提交 `df1fee6 feat: implement bounded agent execution loop`，包含循环、测试与配套文档；提交后工作区干净，Phase 2 收尾完成。
下一单元为 Phase 3 的 [工具参数契约与 JSON Schema](tool-arguments.md)。本讲义保留本单元的实际验收边界，当前功能以 docs/status.md 为准。
