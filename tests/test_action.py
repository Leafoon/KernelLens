from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import RequestInputAction, parse_request_input_action


def make_payload():
    return {
        "kind": "request_input",
        "question": "  请提供目标 GPU 型号。  ",
        "reason": "需要据此选择实现与测试方案。",
    }


def test_parse_preserves_text_and_input():
    payload = make_payload()
    original = payload.copy()

    action = parse_request_input_action(payload)

    assert isinstance(action, RequestInputAction)
    assert action.kind == "request_input"
    assert action.question == original["question"]
    assert action.reason == original["reason"]
    assert payload == original


@pytest.mark.parametrize("missing", ["kind", "question", "reason"])
def test_rejects_missing_fields(missing):
    payload = make_payload()
    del payload[missing]

    with pytest.raises(ValueError, match="exactly"):
        parse_request_input_action(payload)


def test_rejects_fields_from_another_action():
    payload = make_payload()
    payload["tool_name"] = "read_source"

    with pytest.raises(ValueError, match="exactly"):
        parse_request_input_action(payload)


@pytest.mark.parametrize("kind", ["call_tool", "finish"])
def test_rejects_other_action_kinds(kind):
    payload = make_payload()
    payload["kind"] = kind

    with pytest.raises(ValueError, match="expected request_input"):
        parse_request_input_action(payload)


@pytest.mark.parametrize("payload", [None, []])
def test_rejects_non_mapping_input(payload):
    with pytest.raises(TypeError, match="mapping"):
        parse_request_input_action(payload)


@pytest.mark.parametrize("name", ["question", "reason"])
@pytest.mark.parametrize("value, error", [(True, TypeError), (" \n\t ", ValueError)])
def test_rejects_invalid_text(name, value, error):
    payload = make_payload()
    payload[name] = value

    with pytest.raises(error, match=name):
        parse_request_input_action(payload)


def test_action_cannot_be_rewritten():
    action = parse_request_input_action(make_payload())

    with pytest.raises(FrozenInstanceError):
        action.question = "改成另一个问题"
