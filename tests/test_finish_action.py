from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import AgentAction, FinishAction


def test_preserves_submission_text():
    answer = "  建议依次运行编译、正确性与性能测试。\n目前没有实际执行结果。  "
    reason = "当前请求只要求验证步骤说明。"

    action: AgentAction = FinishAction(answer=answer, reason=reason)

    assert action.kind == "finish"
    assert action.answer == answer
    assert action.reason == reason


@pytest.mark.parametrize("name", ["answer", "reason"])
@pytest.mark.parametrize("value", [None, True])
def test_rejects_non_string_fields(name, value):
    inputs = {"answer": "建议先运行编译测试。", "reason": "交付验证步骤说明。"}
    inputs[name] = value

    with pytest.raises(TypeError, match=name):
        FinishAction(**inputs)


@pytest.mark.parametrize("name", ["answer", "reason"])
@pytest.mark.parametrize("value", ["", " \n\t "])
def test_rejects_blank_fields(name, value):
    inputs = {"answer": "建议先运行编译测试。", "reason": "交付验证步骤说明。"}
    inputs[name] = value

    with pytest.raises(ValueError, match=name):
        FinishAction(**inputs)


def test_submission_cannot_be_rewritten():
    action = FinishAction(answer="当前没有 GPU 实测结果。", reason="说明验证边界。")

    with pytest.raises(FrozenInstanceError):
        action.answer = "所有测试都通过了"
