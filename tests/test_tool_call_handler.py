import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.handlers import apply_call_tool
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING, task_type=TaskType.DIAGNOSE):
    return TaskState(TaskRequest(task_type, "读取当前 GEMM 的执行报告"), status=status)


def make_action(tool_name="read_report"):
    return CallToolAction(
        tool_name=tool_name,
        arguments={"path": "report.json"},
        reason="读取服务器返回的报告。",
    )


def must_not_run(action):
    pytest.fail("executor must not be called for invalid or stopped tasks")


@pytest.mark.parametrize(
    "task_type", [TaskType.GENERATE, TaskType.OPTIMIZE, TaskType.DIAGNOSE]
)
@pytest.mark.parametrize(
    "execution_status", [ToolExecutionStatus.SUCCEEDED, ToolExecutionStatus.FAILED]
)
def test_returns_observation_without_changing_state(task_type, execution_status):
    state = make_state(task_type=task_type)
    original_verification = state.verification
    action = make_action()
    report = VerificationState(compilation=VerificationStatus.FAILED)
    observation = ToolObservation(action, execution_status, "固定测试反馈。", report)
    calls = []

    def execute(received_action):
        calls.append(received_action)
        return observation

    result = apply_call_tool(state, action, executor=execute)

    assert result is observation
    assert result.action is action
    assert result.status is execution_status
    assert result.verification is report
    assert state.status is TaskStatus.RUNNING
    assert state.verification is original_verification
    assert state.verification.compilation is VerificationStatus.NOT_RUN
    assert len(calls) == 1
    assert calls[0] is action


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_invalid_source_state_does_not_call_executor(status):
    with pytest.raises(ValueError, match="running"):
        apply_call_tool(make_state(status=status), make_action(), executor=must_not_run)


@pytest.mark.parametrize("state", [None, {}])
def test_invalid_state_type_does_not_call_executor(state):
    with pytest.raises(TypeError, match="state"):
        apply_call_tool(state, make_action(), executor=must_not_run)


@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        RequestInputAction(question="请提供报告。", reason="缺少证据。"),
        FinishAction(answer="当前分析已整理。", reason="申请交付。"),
    ],
)
def test_other_actions_do_not_call_executor(action):
    with pytest.raises(TypeError, match="action"):
        apply_call_tool(make_state(), action, executor=must_not_run)


@pytest.mark.parametrize("executor", [None, True])
def test_rejects_non_callable_executor(executor):
    with pytest.raises(TypeError, match="executor"):
        apply_call_tool(make_state(), make_action(), executor=executor)


@pytest.mark.parametrize("result", [None, {}, make_action()])
def test_rejects_invalid_observation_type(result):
    calls = []

    def execute(action):
        calls.append(action)
        return result

    with pytest.raises(TypeError, match="ToolObservation"):
        apply_call_tool(make_state(), make_action(), executor=execute)
    assert len(calls) == 1


@pytest.mark.parametrize("tool_name", ["read_report", "read_source"])
def test_rejects_feedback_for_a_different_action_object(tool_name):
    action = make_action()
    other_action = make_action(tool_name)
    assert other_action is not action
    if tool_name == "read_report":
        assert other_action == action
    observation = ToolObservation(
        other_action, ToolExecutionStatus.SUCCEEDED, "不属于本次行动的反馈。"
    )
    calls = []

    def execute(received_action):
        calls.append(received_action)
        return observation

    with pytest.raises(ValueError, match="original action"):
        apply_call_tool(make_state(), action, executor=execute)
    assert len(calls) == 1
    assert calls[0] is action


def test_executor_exception_propagates_without_retry():
    state = make_state()
    calls = []

    def failing_executor(action):
        calls.append(action)
        raise RuntimeError("executor unavailable")

    with pytest.raises(RuntimeError, match="executor unavailable"):
        apply_call_tool(state, make_action(), executor=failing_executor)
    assert state.status is TaskStatus.RUNNING
    assert len(calls) == 1


def test_failed_observation_can_feed_next_decision():
    state = make_state()
    action = make_action()

    def execute(received_action):
        return ToolObservation(
            received_action, ToolExecutionStatus.FAILED, "报告文件不存在。"
        )

    observation = apply_call_tool(state, action, executor=execute)
    received = []

    def model(received_state, observations):
        received.append((received_state, observations))
        return {
            "kind": "request_input",
            "question": "请提供正确的报告路径。",
            "reason": "读取报告失败，需要补充信息。",
        }

    next_action = decide_once(state, model, (observation,))

    assert isinstance(next_action, RequestInputAction)
    assert state.status is TaskStatus.RUNNING
    assert len(received) == 1
    assert received[0][0] is state
    assert received[0][1][0] is observation
    assert received[0][1][0].status is ToolExecutionStatus.FAILED
