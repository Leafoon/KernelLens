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
