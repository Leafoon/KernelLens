from dataclasses import dataclass, field, replace
from enum import StrEnum

from kernellens.domain.task import TaskRequest
from kernellens.domain.verification import VerificationState


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


_ALLOWED_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_INPUT,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BUDGET_EXHAUSTED,
    },
    TaskStatus.WAITING_INPUT: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.BUDGET_EXHAUSTED: set(),
}


def transition_status(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if not isinstance(current, TaskStatus) or not isinstance(target, TaskStatus):
        raise TypeError("current and target must be TaskStatus values")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"invalid status transition: {current.value} -> {target.value}"
        )
    return target


@dataclass(frozen=True)
class TaskState:
    request: TaskRequest
    status: TaskStatus = TaskStatus.PENDING
    verification: VerificationState = field(default_factory=VerificationState)

    def __post_init__(self) -> None:
        if not isinstance(self.request, TaskRequest):
            raise TypeError("request must be a TaskRequest")
        if not isinstance(self.status, TaskStatus):
            raise TypeError("status must be a TaskStatus")
        if not isinstance(self.verification, VerificationState):
            raise TypeError("verification must be a VerificationState")

    def transition_to(self, target: TaskStatus) -> "TaskState":
        next_status = transition_status(self.status, target)
        return replace(self, status=next_status)
