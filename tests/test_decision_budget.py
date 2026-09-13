from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget, DecisionBudgetExhausted
from kernellens.runtime.step import decide_once


def test_consume_returns_a_new_budget_snapshot():
    original = DecisionBudget(max_decisions=2)

    updated = original.consume()

    assert original.used_decisions == 0
    assert updated.used_decisions == 1
    assert updated.max_decisions == 2
    assert updated is not original


def test_allows_exactly_the_configured_number_of_attempts():
    budget = DecisionBudget(max_decisions=2)

    for expected in (1, 2):
        budget = budget.consume()
        assert budget.used_decisions == expected

    for _ in range(2):
        with pytest.raises(DecisionBudgetExhausted):
            budget = budget.consume()
        assert budget.used_decisions == 2


@pytest.mark.parametrize("field", ["max_decisions", "used_decisions"])
@pytest.mark.parametrize("value", [True, False, 1.5, "2", None])
def test_rejects_non_integer_budget_fields(field, value):
    values = {"max_decisions": 2, "used_decisions": 0}
    values[field] = value

    with pytest.raises(TypeError, match=field):
        DecisionBudget(**values)


@pytest.mark.parametrize("limit", [0, -1])
def test_rejects_non_positive_limits(limit):
    with pytest.raises(ValueError, match="max_decisions"):
        DecisionBudget(max_decisions=limit)


@pytest.mark.parametrize("used", [-1, 3])
def test_rejects_usage_outside_the_limit(used):
    with pytest.raises(ValueError, match="used_decisions"):
        DecisionBudget(max_decisions=2, used_decisions=used)


@pytest.mark.parametrize("field", ["max_decisions", "used_decisions"])
def test_budget_fields_are_frozen(field):
    budget = DecisionBudget(max_decisions=2)

    with pytest.raises(FrozenInstanceError):
        setattr(budget, field, 0)


def test_model_failure_does_not_refund_consumed_budget():
    state = TaskState(
        TaskRequest(TaskType.DIAGNOSE, "诊断 GEMM 编译失败"),
        status=TaskStatus.RUNNING,
    )
    budget = DecisionBudget(max_decisions=1)
    calls = []

    def failing_model(received_state, observations):
        calls.append(received_state)
        raise RuntimeError("model unavailable")

    budget = budget.consume()
    with pytest.raises(RuntimeError, match="model unavailable"):
        decide_once(state, failing_model)

    assert budget.used_decisions == 1
    assert len(calls) == 1
    assert state.status is TaskStatus.RUNNING

    with pytest.raises(DecisionBudgetExhausted):
        budget = budget.consume()
        decide_once(state, failing_model)
    assert len(calls) == 1
