from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.task import TaskRequest, TaskType


@pytest.mark.parametrize("task_type", list(TaskType))
def test_accepts_task_types_and_preserves_goal(task_type):
    goal = "  处理这个 GEMM 算子需求\n"

    request = TaskRequest(task_type=task_type, goal=goal)

    assert request.task_type is task_type
    assert request.goal == goal


@pytest.mark.parametrize("goal", ["", " \n\t"])
def test_rejects_blank_goal(goal):
    with pytest.raises(ValueError, match="goal"):
        TaskRequest(task_type=TaskType.GENERATE, goal=goal)


def test_rejects_raw_task_type_string():
    with pytest.raises(TypeError, match="task_type"):
        TaskRequest(task_type="generate", goal="生成 GEMM")


def test_rejects_non_string_goal():
    with pytest.raises(TypeError, match="goal"):
        TaskRequest(task_type=TaskType.GENERATE, goal=None)


def test_original_goal_cannot_be_reassigned():
    request = TaskRequest(task_type=TaskType.GENERATE, goal="生成 GEMM")

    with pytest.raises(FrozenInstanceError):
        request.goal = "改为诊断"
