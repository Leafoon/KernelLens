from collections.abc import Callable, Mapping

from kernellens.domain.action import AgentAction, parse_agent_action
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus

type DecisionModel = Callable[
    [TaskState, tuple[ToolObservation, ...]],
    Mapping[str, object],
]


def decide_once(
    state: TaskState,
    model: DecisionModel,
    observations: tuple[ToolObservation, ...] = (),
) -> AgentAction:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if state.status is not TaskStatus.RUNNING:
        raise ValueError("state must be running before a decision")
    if not callable(model):
        raise TypeError("model must be callable")
    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if any(not isinstance(item, ToolObservation) for item in observations):
        raise TypeError("observations must contain only ToolObservation values")

    payload = model(state, observations)
    return parse_agent_action(payload)
