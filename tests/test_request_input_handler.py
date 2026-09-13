import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.handlers import apply_request_input
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING, task_type=TaskType.DIAGNOSE):
    return TaskState(
        request=TaskRequest(task_type, "完善 GEMM 开发需求"),
        status=status,
        verification=VerificationState(syntax=VerificationStatus.PASSED),
    )


def make_action():
    return RequestInputAction(
        question="请提供 GEMM 的 shape 和 dtype。",
        reason="当前计算契约不完整。",
    )


@pytest.mark.parametrize(
    "task_type", [TaskType.GENERATE, TaskType.OPTIMIZE, TaskType.DIAGNOSE]
)
def test_pauses_task_and_preserves_existing_information(task_type):
    original = make_state(task_type=task_type)
    action = make_action()

    paused = apply_request_input(original, action)

    assert paused.status is TaskStatus.WAITING_INPUT
    assert original.status is TaskStatus.RUNNING
    assert paused is not original
    assert paused.request is original.request
    assert paused.verification is original.verification
    assert paused.verification.syntax is VerificationStatus.PASSED
    assert paused.verification.compilation is VerificationStatus.NOT_RUN
    assert action.question == "请提供 GEMM 的 shape 和 dtype。"


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_rejects_invalid_source_states(status):
    with pytest.raises(ValueError, match="invalid status transition"):
        apply_request_input(make_state(status=status), make_action())


@pytest.mark.parametrize("state", [None, {}])
def test_rejects_non_task_state(state):
    with pytest.raises(TypeError, match="state"):
        apply_request_input(state, make_action())


@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        FinishAction(answer="提交当前分析。", reason="本轮分析结束。"),
        CallToolAction(
            tool_name="read_report",
            arguments={"path": "report.json"},
            reason="读取报告。",
        ),
    ],
)
def test_rejects_other_actions(action):
    with pytest.raises(TypeError, match="action"):
        apply_request_input(make_state(), action)


def test_paused_task_cannot_start_another_decision():
    paused = apply_request_input(make_state(), make_action())

    def must_not_run(state, observations):
        pytest.fail("model must not be called while waiting for input")

    with pytest.raises(ValueError, match="running"):
        decide_once(paused, must_not_run)
    assert paused.status is TaskStatus.WAITING_INPUT
