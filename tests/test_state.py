import pytest

from kernellens.domain.state import TaskStatus, transition_status


def test_task_can_wait_resume_and_complete():
    status = TaskStatus.PENDING
    for target in (
        TaskStatus.RUNNING,
        TaskStatus.WAITING_INPUT,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
    ):
        status = transition_status(status, target)
        assert status is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.PENDING),
        (TaskStatus.WAITING_INPUT, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.RUNNING),
    ],
)
def test_invalid_transition_preserves_current_status(current, target):
    status = current
    with pytest.raises(ValueError, match=f"{current.value} -> {target.value}"):
        status = transition_status(status, target)
    assert status is current


@pytest.mark.parametrize(
    "terminal",
    [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BUDGET_EXHAUSTED,
    ],
)
@pytest.mark.parametrize("target", list(TaskStatus))
def test_terminal_states_have_no_exit(terminal, target):
    with pytest.raises(ValueError):
        transition_status(terminal, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("running", TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, "completed"),
    ],
)
def test_rejects_raw_status_strings(current, target):
    with pytest.raises(TypeError, match="TaskStatus"):
        transition_status(current, target)


def test_task_can_be_cancelled_before_starting():
    assert (
        transition_status(TaskStatus.PENDING, TaskStatus.CANCELLED)
        is TaskStatus.CANCELLED
    )


@pytest.mark.parametrize(
    "target",
    [TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BUDGET_EXHAUSTED],
)
def test_running_task_can_stop_without_completion(target):
    assert transition_status(TaskStatus.RUNNING, target) is target
