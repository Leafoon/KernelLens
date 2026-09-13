import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING):
    return TaskState(
        request=TaskRequest(TaskType.DIAGNOSE, "说明报告读取情况"),
        status=status,
    )


def finish_payload():
    return {
        "kind": "finish",
        "answer": "当前只提交读取情况说明，未确认算子验证通过。",
        "reason": "提供本轮说明。",
    }


def must_not_run(state, observations):
    pytest.fail("model must not be called for invalid runtime input")


def test_calls_model_once_and_preserves_state():
    state = make_state()
    calls = []

    def fake_model(received_state, observations):
        calls.append((received_state, observations))
        return finish_payload()

    action = decide_once(state, fake_model)

    assert isinstance(action, FinishAction)
    assert action.answer == finish_payload()["answer"]
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] == ()
    assert state.status is TaskStatus.RUNNING


def test_passes_feedback_to_the_model():
    state = make_state()
    proposal = CallToolAction(
        tool_name="read_verification_report",
        arguments={"path": "reports/compile.json"},
        reason="读取回传报告。",
    )
    history = (
        ToolObservation(
            action=proposal,
            status=ToolExecutionStatus.FAILED,
            content="没有找到报告文件。",
        ),
    )
    calls = []

    def fake_model(received_state, observations):
        calls.append((received_state, observations))
        if observations[-1].status is ToolExecutionStatus.FAILED:
            return {
                "kind": "request_input",
                "question": "请确认报告文件路径。",
                "reason": "本轮没有取得报告。",
            }
        return finish_payload()

    action = decide_once(state, fake_model, observations=history)

    assert isinstance(action, RequestInputAction)
    assert action.question == "请确认报告文件路径。"
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] is history
    assert state.status is TaskStatus.RUNNING


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_rejects_non_running_tasks_before_calling_model(status):
    with pytest.raises(ValueError, match="running"):
        decide_once(make_state(status), must_not_run)


@pytest.mark.parametrize("state", [None, {}])
def test_rejects_invalid_state_before_calling_model(state):
    with pytest.raises(TypeError, match="state"):
        decide_once(state, must_not_run)


@pytest.mark.parametrize("observations", [None, [], (None,)])
def test_rejects_invalid_feedback_before_calling_model(observations):
    with pytest.raises(TypeError, match="observations"):
        decide_once(make_state(), must_not_run, observations=observations)


@pytest.mark.parametrize("model", [None, 42])
def test_rejects_non_callable_model(model):
    with pytest.raises(TypeError, match="callable"):
        decide_once(make_state(), model)


@pytest.mark.parametrize(
    "payload, error",
    [(None, TypeError), ({"kind": "unknown"}, ValueError)],
)
def test_rejects_invalid_model_output_without_retry(payload, error):
    calls = []

    def fake_model(state, observations):
        calls.append(state)
        return payload

    with pytest.raises(error):
        decide_once(make_state(), fake_model)
    assert len(calls) == 1


def test_model_exception_propagates_without_retry():
    calls = []

    def failing_model(state, observations):
        calls.append(state)
        raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        decide_once(make_state(), failing_model)
    assert len(calls) == 1
