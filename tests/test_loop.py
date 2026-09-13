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
