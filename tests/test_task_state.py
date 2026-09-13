from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus


def test_new_task_starts_pending_with_unrun_checks():
    request = TaskRequest(TaskType.GENERATE, "生成基础 GEMM")
    state = TaskState(request=request)

    assert state.request is request
    assert state.status is TaskStatus.PENDING
    assert state.verification == VerificationState()


def test_transition_preserves_request_and_verification():
    request = TaskRequest(TaskType.DIAGNOSE, "  分析服务器编译失败  ")
    checks = VerificationState(compilation=VerificationStatus.FAILED)
    before = TaskState(request=request, verification=checks)

    after = before.transition_to(TaskStatus.RUNNING)

    assert after is not before
    assert before.status is TaskStatus.PENDING
    assert after.status is TaskStatus.RUNNING
    assert after.request is request
    assert after.verification is checks


def test_completion_does_not_mark_checks_as_passed():
    state = TaskState(TaskRequest(TaskType.GENERATE, "交付 GEMM 候选和运行说明"))
    running = state.transition_to(TaskStatus.RUNNING)

    completed = running.transition_to(TaskStatus.COMPLETED)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.verification is running.verification
    assert completed.verification == VerificationState()


def test_illegal_transition_preserves_current_snapshot():
    state = TaskState(TaskRequest(TaskType.OPTIMIZE, "提出 GEMM 优化候选"))

    with pytest.raises(ValueError, match="pending -> completed"):
        state = state.transition_to(TaskStatus.COMPLETED)

    assert state.status is TaskStatus.PENDING


@pytest.mark.parametrize("target", ["running", VerificationStatus.FAILED])
def test_transition_rejects_wrong_target_type(target):
    state = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))

    with pytest.raises(TypeError, match="TaskStatus"):
        state.transition_to(target)

    assert state.status is TaskStatus.PENDING


@pytest.mark.parametrize(
    "field_name, value",
    [("request", None), ("status", "pending"), ("verification", None)],
)
def test_snapshot_rejects_wrong_field_type(field_name, value):
    arguments = {"request": TaskRequest(TaskType.GENERATE, "生成基础 GEMM")}
    arguments[field_name] = value

    with pytest.raises(TypeError, match=field_name):
        TaskState(**arguments)


def test_lifecycle_cannot_be_reassigned_directly():
    state = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))

    with pytest.raises(FrozenInstanceError):
        state.status = TaskStatus.COMPLETED
