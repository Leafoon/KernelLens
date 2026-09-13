# RUN-003G：汇总停止状态、预算与步骤记录

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前处于 Phase 2 — State & Minimal Runtime。RUN-003F 已提交为
`526412f feat: add validated runtime step records`，进入本单元前工作区干净。
进入本单元前，完整验收为 282 个测试及 lint/format、快照观察通过。

StepRecord 能表达一次尝试，但调用者还需要知道整次运行停在哪里、用了多少额度，以及有哪些步骤。
本单元在同一个 records.py 中增加 RunResult，供随后编写的有限循环统一返回。
只实现结果组合与一致性检查；循环、自动记录和持久化保持后续任务。

## Concept

**一次尝试与整次运行。** StepRecord 是一条记录；RunResult 是停止状态、最新预算和完整步骤集合。
如果只返回 TaskState，调用者无法核对已消费额度和失败记录。
如果分开返回多个无约束变量，容易出现“用了两次额度，只留下一个步骤”的错配。
组合为一个冻结对象，可以在返回边界立即发现这种遗漏；不需要新增服务或运行依赖。

**停止不等于任务完成。** WAITING_INPUT 表示当前调用停止等待，但任务尚未完成。
本版拒绝 PENDING 和 RUNNING 的 RunResult，接受现有其余五种停止状态。

**每次决策尝试都需要记录。** 本版汇总从序号 1 开始的完整历史，要求
`len(steps) == budget.used_decisions`，序号依次为 1、2、3……。
模型或解析失败也消耗额度，因此上一单元允许记录只有 error、没有 Action。
当前不支持只传恢复后的增量记录；恢复设计在后续阶段处理。
额度仍不是实际 Provider 请求数、Token 数或成本。

**预算用完与因预算用完停止是两回事。** 最后一个额度产生了合格交付，结果可以是 COMPLETED。
只有还需要继续却没有额度时，才应因预算耗尽停止。
因此 BUDGET_EXHAUSTED 要求 used_decisions == max_decisions，但反方向不成立。
记录类只校验已提供材料，不负责替循环决定何时结束。

## Design

| 字段 | 类型 | 职责 |
| --- | --- | --- |
| state | TaskState | 运行退出时的状态 |
| budget | DecisionBudget | 最新预算快照 |
| steps | tuple[StepRecord, ...]，默认空元组 | 完整、有序的尝试记录 |

校验顺序：字段类型 → 停止状态 → 记录数与预算 → 连续编号 → 请求对象关联 → 预算耗尽状态的依据。
具体流程见 [运行结果汇总图](diagrams/run-result.md)。

每条记录的 `state_after.request` 必须是结果 state 中的原 TaskRequest 对象。
这样可以拒绝明显混入另一个请求的记录，包括字段内容完全相同的新请求对象。
这仍只检查对象关联，不能区分重复执行同一个请求对象产生的不同 run；稳定运行标识后续接入。

**最后记录状态可以早于停止状态。** 假设第 2 次工具行动处理后仍是 RUNNING，
随后循环发现没有第 3 次额度，最终状态成为 BUDGET_EXHAUSTED。
此时只应有 2 条记录，最后记录的状态仍是 RUNNING，结果 state 是 BUDGET_EXHAUSTED。
所以本单元不要求最后的 state_after 与结果 state 是同一个对象。

RunResult 不认证事件发生顺序、完整生命周期、交付审核或验证来源，
例如 COMPLETED 是否由有效 FinishAction 审核产生，仍由 Runtime 的执行路径及测试保证。
记录构造成功不能单独证明业务任务成功；此处只做已列出的集合一致性检查。
所有材料在内存中复用，tuple 和 frozen 限制普通原地修改，不实现落盘或防篡改。

## Implementation

本单元由你扩展一个已有核心文件，并创建一个测试文件。StepRecord 保持原样。

### 1. 扩展 records.py

文件：`src/kernellens/runtime/records.py`。
将已有 `from kernellens.domain.state import TaskState` 这一行替换为下面两行，保留其余导入：

```python
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.runtime.budget import DecisionBudget
```

在 StepRecord 类之后添加 RunResult，两个顶层类之间保留两行空行：

```python
@dataclass(frozen=True)
class RunResult:
    state: TaskState
    budget: DecisionBudget
    steps: tuple[StepRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, TaskState):
            raise TypeError("state must be a TaskState")
        if not isinstance(self.budget, DecisionBudget):
            raise TypeError("budget must be a DecisionBudget")
        if not isinstance(self.steps, tuple):
            raise TypeError("steps must be a tuple")
        if any(not isinstance(step, StepRecord) for step in self.steps):
            raise TypeError("steps must contain only StepRecord values")

        if self.state.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise ValueError("run result must have a stopped state")
        if len(self.steps) != self.budget.used_decisions:
            raise ValueError("step count must match used decisions")
        for expected_number, step in enumerate(self.steps, start=1):
            if step.decision_number != expected_number:
                raise ValueError("step numbers must be consecutive from 1")
            if step.state_after.request is not self.state.request:
                raise ValueError("all steps must reference the same request")
        if (
            self.state.status is TaskStatus.BUDGET_EXHAUSTED
            and self.budget.used_decisions != self.budget.max_decisions
        ):
            raise ValueError("budget must be exhausted for budget_exhausted state")
```

按逻辑块理解：

- `steps=()` 是不可变空元组，可以安全作为默认值；`...` 表示类型注解允许任意数量的 StepRecord。
- 先确保 steps 是 tuple 且所有元素都是 StepRecord，再访问元素的字段。
- 数量检查把额度与记录连接起来；它不能替代实际调用前消费额度的控制逻辑。
- `enumerate(self.steps, start=1)` 同时给出预期序号和记录，避免漏号、重号或乱序。
- 使用 `is` 检查同一个 TaskRequest，不把值相等误当成同一请求对象。
- 最后只检查 BUDGET_EXHAUSTED 的必要条件，不改写已经完成的状态。
- 返回材料复用原对象，不重新计算状态、消费额度或复制一套相同记录。

### 2. 创建结果汇总测试

文件：`tests/test_run_result.py`。共 11 个测试函数，参数化后 22 个用例。

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction, FinishAction, RequestInputAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget
from kernellens.runtime.records import RunResult, StepRecord


def make_running_state(goal="诊断当前 GEMM"):
    request = TaskRequest(TaskType.DIAGNOSE, goal)
    return TaskState(request).transition_to(TaskStatus.RUNNING)


def make_tool_step(number, state):
    action = CallToolAction(
        tool_name="read_report",
        arguments={"path": "report.json"},
        reason="读取执行反馈。",
    )
    observation = ToolObservation(
        action, ToolExecutionStatus.FAILED, "报告文件不存在。"
    )
    return StepRecord(number, state, action, observation)


def make_stopped_step(status):
    state = make_running_state().transition_to(status)
    if status is TaskStatus.WAITING_INPUT:
        action = RequestInputAction(question="请提供报告。", reason="缺少材料。")
        return StepRecord(1, state, action)
    if status is TaskStatus.COMPLETED:
        action = FinishAction(answer="提交当前建议。", reason="固定测试材料。")
        return StepRecord(1, state, action)
    return StepRecord(1, state, error="model unavailable")


@pytest.mark.parametrize(
    "status", [TaskStatus.WAITING_INPUT, TaskStatus.COMPLETED, TaskStatus.FAILED]
)
def test_preserves_stopped_state_budget_and_records(status):
    record = make_stopped_step(status)
    budget = DecisionBudget(2, 1)
    steps = (record,)

    result = RunResult(record.state_after, budget, steps)

    assert result.state is record.state_after
    assert result.budget is budget
    assert result.steps is steps
    assert result.steps[0] is record


def test_allows_cancellation_before_first_decision():
    state = TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"))
    cancelled = state.transition_to(TaskStatus.CANCELLED)

    result = RunResult(cancelled, DecisionBudget(2))

    assert result.state is cancelled
    assert result.budget.used_decisions == 0
    assert result.steps == ()


def test_budget_stop_does_not_create_a_phantom_decision():
    running = make_running_state()
    steps = (make_tool_step(1, running), make_tool_step(2, running))
    stopped = running.transition_to(TaskStatus.BUDGET_EXHAUSTED)

    result = RunResult(stopped, DecisionBudget(2, 2), steps)

    assert result.state.status is TaskStatus.BUDGET_EXHAUSTED
    assert result.steps[-1].state_after.status is TaskStatus.RUNNING
    assert result.state.verification is result.steps[-1].state_after.verification
    assert len(result.steps) == result.budget.used_decisions == 2


@pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.RUNNING])
def test_rejects_unstopped_state(status):
    state = TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"), status=status)
    with pytest.raises(ValueError, match="stopped state"):
        RunResult(state, DecisionBudget(2))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", None),
        ("budget", None),
        ("steps", []),
        ("steps", (None,)),
    ],
)
def test_rejects_invalid_field_types(field, value):
    record = make_stopped_step(TaskStatus.FAILED)
    values = {
        "state": record.state_after,
        "budget": DecisionBudget(2, 1),
        "steps": (record,),
    }
    values[field] = value
    with pytest.raises(TypeError, match=field):
        RunResult(**values)


@pytest.mark.parametrize("used", [0, 2])
def test_rejects_missing_or_extra_records(used):
    record = make_stopped_step(TaskStatus.FAILED)
    with pytest.raises(ValueError, match="step count"):
        RunResult(record.state_after, DecisionBudget(2, used), (record,))


@pytest.mark.parametrize("numbers", [(2,), (1, 1), (2, 1), (1, 3)])
def test_rejects_gaps_duplicates_and_reordered_numbers(numbers):
    running = make_running_state()
    steps = tuple(make_tool_step(number, running) for number in numbers)
    stopped = running.transition_to(TaskStatus.CANCELLED)

    with pytest.raises(ValueError, match="consecutive"):
        RunResult(stopped, DecisionBudget(3, len(steps)), steps)


@pytest.mark.parametrize("goal", ["诊断当前 GEMM", "诊断另一份 GEMM"])
def test_rejects_records_from_another_request_object(goal):
    running = make_running_state()
    other = make_running_state(goal)
    assert other.request is not running.request
    if goal == running.request.goal:
        assert other.request == running.request
    steps = (make_tool_step(1, other),)
    stopped = running.transition_to(TaskStatus.CANCELLED)

    with pytest.raises(ValueError, match="same request"):
        RunResult(stopped, DecisionBudget(2, 1), steps)


def test_rejects_budget_stop_with_allowance_remaining():
    running = make_running_state()
    steps = (make_tool_step(1, running),)
    stopped = running.transition_to(TaskStatus.BUDGET_EXHAUSTED)

    with pytest.raises(ValueError, match="budget must be exhausted"):
        RunResult(stopped, DecisionBudget(2, 1), steps)


def test_completion_on_last_allowance_stays_completed():
    record = make_stopped_step(TaskStatus.COMPLETED)

    result = RunResult(record.state_after, DecisionBudget(1, 1), (record,))

    assert result.state.status is TaskStatus.COMPLETED
    assert result.budget.used_decisions == result.budget.max_decisions


def test_result_and_record_sequence_are_immutable():
    record = make_stopped_step(TaskStatus.FAILED)
    result = RunResult(record.state_after, DecisionBudget(2, 1), (record,))

    with pytest.raises(FrozenInstanceError):
        result.steps = ()
    with pytest.raises(TypeError):
        result.steps[0] = record
```

| 测试组 | 用例数 | 验证目的 |
| --- | ---: | --- |
| 等待／完成／失败结果 | 3 | 保留原状态、预算与记录元组 |
| 首次决策前取消 | 1 | 零用量与空记录可表达提前取消 |
| 预算耗尽停止 | 1 | 最终状态和最后步骤状态可不同，不虚构新尝试 |
| 未停止状态 | 2 | PENDING / RUNNING 不能作为结果返回 |
| 非法字段类型 | 4 | 检查 state、budget、tuple 和 tuple 元素 |
| 记录数量不匹配 | 2 | 防止丢记录或多记记录 |
| 非连续编号 | 4 | 拒绝错误起点、重复、乱序和缺号 |
| 其他请求对象 | 2 | 同内容新请求与不同内容请求都不能混入 |
| 仍有额度却声称耗尽 | 1 | 停止状态必须有预算依据 |
| 最后额度上完成 | 1 | 用完额度不应覆盖完成状态 |
| 冻结结果与元组 | 1 | 不能通过普通赋值或元素写入改动结果 |

测试材料手工构造，不执行真实模型、工具或审核。
辅助函数 make_stopped_step 只准备测试输入，不是生产 Runtime 的状态处理逻辑。
这些用例不证明实际循环已正确执行；下一单元会把返回契约接入控制流程。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_run_result.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

2026-09-10 实际验收：用户实现与测试 Review 通过；完整回归 **304 passed（0.11s）= 282 + 22**，包含全部新增用例。
助手使用 `uv run --locked --offline --no-cache --no-python-downloads pytest -q`；Ruff lint 和格式检查通过（30 个 Python 文件）。
RunResult 与测试 AST 均与讲义一致，已有 StepRecord AST 与提交版本一致。
助手只整理 records.py 的空行与末尾换行，写入前确认 AST 和非空白内容均不变；未修改核心逻辑或测试。

## Observe

以下手工材料示例已验证，没有实际发起决策或执行工具。
重点观察最终停止状态与最后一次尝试状态的区别，以及丢失记录时的报错。

```bash
uv run --locked python - <<'PY'
from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget
from kernellens.runtime.records import RunResult, StepRecord


running = TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"))
running = running.transition_to(TaskStatus.RUNNING)
action = CallToolAction(
    tool_name="read_report",
    arguments={"path": "report.json"},
    reason="读取执行反馈。",
)
observation = ToolObservation(
    action, ToolExecutionStatus.FAILED, "报告文件不存在。"
)
step = StepRecord(1, running, action, observation)
budget = DecisionBudget(1).consume()
stopped = running.transition_to(TaskStatus.BUDGET_EXHAUSTED)

result = RunResult(stopped, budget, (step,))
print(result.state.status.value)
print(result.budget.used_decisions)
print(len(result.steps))
print(result.steps[-1].state_after.status.value)

try:
    RunResult(stopped, budget, ())
except ValueError as error:
    print(error)
PY
```

2026-09-10 实际输出：

```text
budget_exhausted
1
1
running
step count must match used decisions
```

已有 1 次额度和 1 条记录，结果在尝试之外因额度不足停止，没有第 2 条虚构记录。
把记录清空却保留已用额度，会立即触发一致性错误。
验收还通过额外断言核对了原状态、预算、请求、记录、行动、反馈及验证对象的引用。
真正由循环计数、创建记录和结束任务，要在接入 Runtime 后再验证。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 空元组或列表混用 | steps 类型测试失败 | 用 list 替代 tuple，或把单个记录放在普通括号里 | 单条记录用 (record,)，完整列表在调用边界转换为 tuple |
| 已用次数与记录数不同 | step count 错误 | 漏记失败或复用旧预算快照 | 核对每次尝试的消费与记录，不随意重置预算消除报错 |
| 编号第一项是 0 | consecutive 错误 | enumerate 使用默认起点 | 明确 start=1，首个消费后的序号是 1 |
| 内容相同仍被拒绝 | same request 错误 | 重新构造了 TaskRequest | 同一次运行传递原请求对象，状态转换保留引用 |
| 耗尽时多出一个步骤 | 预算停止测试失败 | 为未开始的决策创建记录 | 停止状态与步骤分开表达，不虚构尝试 |
| 用完额度后完成态被覆盖 | 最后额度完成测试失败 | 把用量等于上限直接当作停止原因 | 保留已经产生的完成状态，仅在继续受阻时因预算停止 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位；核心修复由你完成。

## Checkpoint

本单元应理解：尝试记录与运行结果、数量及顺序不变量、对象归属，以及预算用尽与停止原因的区别。
RunResult 和 22 个新用例已由你实现并验收；全量 304 个测试、lint/format 和汇总观察通过。
当前代码与配套文档组成一个完整、可验证的小单元，适合保存为一次 Commit。

已核对提交 `8b7ccf5 feat: add validated runtime results`，包含结果模型、测试和配套文档；提交后工作区干净。
本单元完成；下一学习单元见 [有限循环与自动记录](agent-loop.md)。
