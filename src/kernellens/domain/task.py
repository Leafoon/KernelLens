from dataclasses import dataclass
from enum import StrEnum


class TaskType(StrEnum):
    GENERATE = "generate"
    OPTIMIZE = "optimize"
    DIAGNOSE = "diagnose"


@dataclass(frozen=True)
class TaskRequest:
    task_type: TaskType
    goal: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_type, TaskType):
            raise TypeError("task_type must be a TaskType")
        if not isinstance(self.goal, str):
            raise TypeError("goal must be a string")
        if not self.goal.strip():
            raise ValueError("goal must not be blank")
