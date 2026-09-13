from dataclasses import dataclass

from kernellens.domain.action import (
    AgentAction,
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.runtime.budget import DecisionBudget


@dataclass(frozen=True)
class StepRecord:
    decision_number: int
    state_after: TaskState
    action: AgentAction | None = None
    observation: ToolObservation | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.decision_number, bool) or not isinstance(
            self.decision_number, int
        ):
            raise TypeError("decision_number must be an integer, not bool")
        if self.decision_number < 1:
            raise ValueError("decision_number must be positive")
        if not isinstance(self.state_after, TaskState):
            raise TypeError("state_after must be a TaskState")
        if self.action is not None and not isinstance(
            self.action, (RequestInputAction, CallToolAction, FinishAction)
        ):
            raise TypeError("action must be an AgentAction or None")
        if self.observation is not None and not isinstance(
            self.observation, ToolObservation
        ):
            raise TypeError("observation must be a ToolObservation or None")
        if self.error is not None:
            if not isinstance(self.error, str):
                raise TypeError("error must be a string or None")
            if not self.error.strip():
                raise ValueError("error must not be blank")

        if self.action is None and self.error is None:
            raise ValueError("record must contain an action or error")
        if self.observation is not None:
            if (
                not isinstance(self.action, CallToolAction)
                or self.observation.action is not self.action
            ):
                raise ValueError("observation must reference the recorded tool action")
            if self.error is not None:
                raise ValueError("record cannot contain both observation and error")
        if (
            isinstance(self.action, CallToolAction)
            and self.observation is None
            and self.error is None
        ):
            raise ValueError("tool action record must contain observation or error")


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
