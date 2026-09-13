from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction, FinishAction, RequestInputAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.records import StepRecord


def make_state(status=TaskStatus.RUNNING):
    return TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"), status=status)


def make_tool_action():
    return CallToolAction(
        tool_name="read_report",
        arguments={"path": "report.json"},
        reason="读取执行反馈。",
    )


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (
            RequestInputAction(question="请提供报告。", reason="缺少证据。"),
            TaskStatus.WAITING_INPUT,
        ),
        (
            FinishAction(answer="提交诊断建议。", reason="本轮交付已审核。"),
            TaskStatus.COMPLETED,
        ),
    ],
)
def test_records_non_tool_actions(action, status):
    state = make_state(status)
    record = StepRecord(1, state, action)

    assert record.decision_number == 1
    assert record.state_after is state
    assert record.action is action
    assert record.observation is None
    assert record.error is None


@pytest.mark.parametrize(
    "status", [ToolExecutionStatus.SUCCEEDED, ToolExecutionStatus.FAILED]
)
def test_records_tool_feedback_without_merging_checks(status):
    state = make_state()
    action = make_tool_action()
    report = VerificationState(compilation=VerificationStatus.FAILED)
    observation = ToolObservation(action, status, "固定报告反馈。", report)

    record = StepRecord(2, state, action, observation)

    assert record.decision_number == 2
    assert record.state_after is state
    assert record.action is action
    assert record.observation is observation
    assert record.observation.verification is report
    assert record.state_after.verification.compilation is VerificationStatus.NOT_RUN
    assert record.error is None


@pytest.mark.parametrize(
    "action",
    [
        None,
        make_tool_action(),
        FinishAction(answer="提交当前建议。", reason="申请审核。"),
    ],
)
def test_records_errors_before_or_after_action(action):
    state = make_state(TaskStatus.FAILED)
    error = "  dependency unavailable\n"

    record = StepRecord(1, state, action, error=error)

    assert record.state_after is state
    assert record.action is action
    assert record.error == error
    assert record.observation is None


@pytest.mark.parametrize(
    ("number", "expected_error"),
    [
        (True, TypeError),
        (1.5, TypeError),
        ("1", TypeError),
        (None, TypeError),
        (0, ValueError),
        (-1, ValueError),
    ],
)
def test_rejects_invalid_decision_number(number, expected_error):
    with pytest.raises(expected_error, match="decision_number"):
        StepRecord(number, make_state(), error="model unavailable")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_after", None),
        ("action", {}),
        ("observation", {}),
        ("error", 1),
    ],
)
def test_rejects_invalid_field_types(field, value):
    values = {
        "decision_number": 1,
        "state_after": make_state(),
        "error": "model unavailable",
    }
    values[field] = value
    with pytest.raises(TypeError, match=field):
        StepRecord(**values)


@pytest.mark.parametrize("error", ["", "   "])
def test_rejects_blank_error(error):
    with pytest.raises(ValueError, match="blank"):
        StepRecord(1, make_state(), error=error)


@pytest.mark.parametrize("action", [None, make_tool_action()])
def test_rejects_records_without_an_outcome(action):
    with pytest.raises(ValueError, match="record must contain"):
        StepRecord(1, make_state(), action)


@pytest.mark.parametrize(
    "action",
    [
        RequestInputAction(question="请提供报告。", reason="信息不足。"),
        FinishAction(answer="提交当前建议。", reason="申请审核。"),
        make_tool_action(),
    ],
)
def test_rejects_observation_for_a_different_recorded_action(action):
    original_action = make_tool_action()
    assert original_action is not action
    if isinstance(action, CallToolAction):
        assert original_action == action
    observation = ToolObservation(
        original_action, ToolExecutionStatus.SUCCEEDED, "工具反馈。"
    )

    with pytest.raises(ValueError, match="recorded tool action"):
        StepRecord(1, make_state(), action, observation)


def test_rejects_observation_and_error_together():
    action = make_tool_action()
    observation = ToolObservation(action, ToolExecutionStatus.FAILED, "文件不存在。")

    with pytest.raises(ValueError, match="both observation and error"):
        StepRecord(1, make_state(), action, observation, error="executor unavailable")


def test_record_is_frozen():
    record = StepRecord(1, make_state(TaskStatus.FAILED), error="model unavailable")

    with pytest.raises(FrozenInstanceError):
        record.decision_number = 2
