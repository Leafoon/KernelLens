from collections.abc import Callable

from kernellens.domain.action import (
    AgentAction,
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.runtime.budget import DecisionBudget, DecisionBudgetExhausted
from kernellens.runtime.handlers import (
    FinishRejected,
    FinishReviewer,
    ToolExecutor,
    apply_call_tool,
    apply_finish,
    apply_request_input,
)
from kernellens.runtime.records import RunResult, StepRecord
from kernellens.runtime.step import DecisionModel, decide_once


def run_agent(
    state: TaskState,
    *,
    budget: DecisionBudget,
    model: DecisionModel,
    executor: ToolExecutor,
    reviewer: FinishReviewer,
    on_step: Callable[[StepRecord], None] | None = None,
    on_rejection: Callable[[str], None] | None = None,
) -> RunResult:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(budget, DecisionBudget):
        raise TypeError("budget must be a DecisionBudget")
    if state.status is not TaskStatus.PENDING:
        raise ValueError("state must be pending for a new run")
    if budget.used_decisions != 0:
        raise ValueError("budget must be unused for a new run")
    for name, dependency in (
        ("model", model),
        ("executor", executor),
        ("reviewer", reviewer),
    ):
        if not callable(dependency):
            raise TypeError(f"{name} must be callable")
    for callback in (on_step, on_rejection):
        if callback is not None and not callable(callback):
            raise TypeError("runtime callbacks must be callable")

    state = state.transition_to(TaskStatus.RUNNING)
    observations: tuple[ToolObservation, ...] = ()
    steps: list[StepRecord] = []

    while state.status is TaskStatus.RUNNING:
        try:
            budget = budget.consume()
        except DecisionBudgetExhausted:
            state = state.transition_to(TaskStatus.BUDGET_EXHAUSTED)
            break

        action: AgentAction | None = None
        observation: ToolObservation | None = None
        error: str | None = None
        try:
            action = decide_once(state, model, observations)
            if isinstance(action, RequestInputAction):
                state = apply_request_input(state, action)
            elif isinstance(action, FinishAction):
                state = apply_finish(state, action, reviewer=reviewer)
            elif isinstance(action, CallToolAction):
                observation = apply_call_tool(state, action, executor=executor)
                observations += (observation,)
            else:
                raise TypeError("unsupported agent action")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, FinishRejected) and on_rejection is not None:
                on_rejection(str(exc))
            else:
                state = state.transition_to(TaskStatus.FAILED)

        steps.append(
            StepRecord(budget.used_decisions, state, action, observation, error)
        )
        if on_step is not None:
            on_step(steps[-1])

    return RunResult(state, budget, tuple(steps))
