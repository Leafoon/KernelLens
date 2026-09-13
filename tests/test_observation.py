from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction, FinishAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskStatus
from kernellens.domain.verification import VerificationState, VerificationStatus


def make_inputs():
    return {
        "action": CallToolAction(
            tool_name="read_verification_report",
            arguments={"path": "reports/compile.json"},
            reason="了解服务器回传的检查结果。",
        ),
        "status": ToolExecutionStatus.SUCCEEDED,
        "content": "  本次工具调用的反馈。\n保留原始格式。  ",
    }


@pytest.mark.parametrize("status", list(ToolExecutionStatus))
def test_preserves_feedback_without_a_verification_report(status):
    inputs = make_inputs()
    inputs["status"] = status

    observation = ToolObservation(**inputs)

    assert observation.action is inputs["action"]
    assert observation.status is status
    assert observation.content == inputs["content"]
    assert observation.verification is None


def test_successful_tool_can_report_failed_compilation():
    inputs = make_inputs()
    inputs["content"] = "读取报告成功；报告记录编译失败。"
    checks = VerificationState(compilation=VerificationStatus.FAILED)

    observation = ToolObservation(**inputs, verification=checks)

    assert observation.status is ToolExecutionStatus.SUCCEEDED
    assert observation.verification is checks
    assert observation.verification.compilation is VerificationStatus.FAILED


def test_missing_report_differs_from_checks_not_run():
    inputs = make_inputs()
    checks = VerificationState()

    without_report = ToolObservation(**inputs)
    with_report = ToolObservation(**inputs, verification=checks)

    assert without_report.verification is None
    assert with_report.verification is checks
    assert with_report.verification.compilation is VerificationStatus.NOT_RUN


@pytest.mark.parametrize(
    "name, value",
    [
        ("action", None),
        ("action", FinishAction(answer="交付说明。", reason="准备提交。")),
        ("status", "succeeded"),
        ("status", TaskStatus.FAILED),
        ("status", VerificationStatus.FAILED),
        ("content", None),
        ("content", True),
        ("verification", {}),
        ("verification", VerificationStatus.PASSED),
    ],
)
def test_rejects_invalid_field_types(name, value):
    inputs = make_inputs()
    inputs[name] = value

    with pytest.raises(TypeError, match=name):
        ToolObservation(**inputs)


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_rejects_blank_feedback(content):
    inputs = make_inputs()
    inputs["content"] = content

    with pytest.raises(ValueError, match="content"):
        ToolObservation(**inputs)


def test_feedback_status_cannot_be_rewritten():
    observation = ToolObservation(**make_inputs())

    with pytest.raises(FrozenInstanceError):
        observation.status = ToolExecutionStatus.FAILED
