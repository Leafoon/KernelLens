from collections.abc import Callable

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus, transition_status

type FinishReviewer = Callable[[TaskState, FinishAction], bool]
type ToolExecutor = Callable[[CallToolAction], ToolObservation]


class FinishRejected(RuntimeError):
    """Raised when a finish proposal is not accepted."""


def apply_request_input(
    state: TaskState,
    action: RequestInputAction,
) -> TaskState:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(action, RequestInputAction):
        raise TypeError("action must be a RequestInputAction")
    return state.transition_to(TaskStatus.WAITING_INPUT)


def apply_finish(
    state: TaskState,
    action: FinishAction,
    *,
    reviewer: FinishReviewer,
) -> TaskState:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(action, FinishAction):
        raise TypeError("action must be a FinishAction")
    if not callable(reviewer):
        raise TypeError("reviewer must be callable")

    next_status = transition_status(state.status, TaskStatus.COMPLETED)
    accepted = reviewer(state, action)
    if not isinstance(accepted, bool):
        raise TypeError("reviewer must return a bool")
    if not accepted:
        raise FinishRejected("finish action was rejected")
    return state.transition_to(next_status)


def apply_call_tool(
    state: TaskState,
    action: CallToolAction,
    *,
    executor: ToolExecutor,
) -> ToolObservation:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if state.status is not TaskStatus.RUNNING:
        raise ValueError("state must be running before tool execution")
    if not isinstance(action, CallToolAction):
        raise TypeError("action must be a CallToolAction")
    if not callable(executor):
        raise TypeError("executor must be callable")

    observation = executor(action)
    if not isinstance(observation, ToolObservation):
        raise TypeError("executor must return a ToolObservation")
    if observation.action is not action:
        raise ValueError("observation must reference the original action")
    return observation
