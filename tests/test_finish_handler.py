import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.handlers import FinishRejected, apply_finish
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING, task_type=TaskType.DIAGNOSE):
    return TaskState(
        request=TaskRequest(task_type, "交付当前 GEMM 开发结果"),
        status=status,
        verification=VerificationState(syntax=VerificationStatus.PASSED),
    )


def make_action():
    return FinishAction(
        answer="提交当前分析与建议，尚未执行服务器编译验证。",
        reason="申请交付本轮结果。",
    )


def must_not_run(state, value):
    pytest.fail("dependency must not be called for invalid or stopped tasks")


@pytest.mark.parametrize(
    "task_type", [TaskType.GENERATE, TaskType.OPTIMIZE, TaskType.DIAGNOSE]
)
def test_acceptance_completes_task_without_changing_verification(task_type):
    state = make_state(task_type=task_type)
    action = make_action()
    calls = []

    def accept(received_state, received_action):
        calls.append((received_state, received_action))
        return True

    completed = apply_finish(state, action, reviewer=accept)

    assert completed.status is TaskStatus.COMPLETED
    assert state.status is TaskStatus.RUNNING
    assert completed.request is state.request
    assert completed.verification is state.verification
    assert completed.verification.syntax is VerificationStatus.PASSED
    assert completed.verification.compilation is VerificationStatus.NOT_RUN
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] is action
    with pytest.raises(ValueError, match="running"):
        decide_once(completed, must_not_run)


def test_rejection_preserves_running_state():
    state = make_state()
    action = make_action()
    calls = []

    def reject(received_state, received_action):
        calls.append(received_action)
        return False

    with pytest.raises(FinishRejected, match="rejected"):
        apply_finish(state, action, reviewer=reject)
    assert state.status is TaskStatus.RUNNING
    assert calls == [action]


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_invalid_source_state_does_not_call_reviewer(status):
    with pytest.raises(ValueError, match="invalid status transition"):
        apply_finish(make_state(status=status), make_action(), reviewer=must_not_run)


@pytest.mark.parametrize("state", [None, {}])
def test_invalid_state_type_does_not_call_reviewer(state):
    with pytest.raises(TypeError, match="state"):
        apply_finish(state, make_action(), reviewer=must_not_run)


@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        RequestInputAction(question="请补全 shape。", reason="信息不足。"),
        CallToolAction(
            tool_name="read_report",
            arguments={"path": "report.json"},
            reason="读取报告。",
        ),
    ],
)
def test_other_actions_do_not_call_reviewer(action):
    with pytest.raises(TypeError, match="action"):
        apply_finish(make_state(), action, reviewer=must_not_run)


@pytest.mark.parametrize("reviewer", [None, True])
def test_rejects_non_callable_reviewer(reviewer):
    with pytest.raises(TypeError, match="reviewer"):
        apply_finish(make_state(), make_action(), reviewer=reviewer)


@pytest.mark.parametrize("verdict", [None, "false", 0, 1])
def test_non_boolean_verdict_does_not_complete_task(verdict):
    state = make_state()
    calls = []

    def invalid_reviewer(received_state, action):
        calls.append(action)
        return verdict

    with pytest.raises(TypeError, match="bool"):
        apply_finish(state, make_action(), reviewer=invalid_reviewer)
    assert state.status is TaskStatus.RUNNING
    assert len(calls) == 1


def test_reviewer_exception_propagates_without_retry():
    state = make_state()
    calls = []

    def failing_reviewer(received_state, action):
        calls.append(action)
        raise RuntimeError("reviewer unavailable")

    with pytest.raises(RuntimeError, match="reviewer unavailable"):
        apply_finish(state, make_action(), reviewer=failing_reviewer)
    assert state.status is TaskStatus.RUNNING
    assert len(calls) == 1
