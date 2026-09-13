from copy import deepcopy

import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
    parse_agent_action,
)


def make_payload(kind):
    return {
        "request_input": {
            "kind": "request_input",
            "question": "  请提供 GPU 型号。  ",
            "reason": "选择目标架构。",
        },
        "call_tool": {
            "kind": "call_tool",
            "tool_name": "search_source",
            "arguments": {"query": "gemm", "limit": 3},
            "reason": "寻找源码依据。",
        },
        "finish": {
            "kind": "finish",
            "answer": "  当前只交付验证步骤。\n尚未运行 GPU 测试。  ",
            "reason": "当前请求已获得步骤说明。",
        },
    }[kind]


@pytest.mark.parametrize(
    "kind, expected_type",
    [
        ("request_input", RequestInputAction),
        ("call_tool", CallToolAction),
        ("finish", FinishAction),
    ],
)
def test_routes_and_preserves_fields(kind, expected_type):
    payload = make_payload(kind)
    original = deepcopy(payload)

    action = parse_agent_action(payload)

    assert isinstance(action, expected_type)
    for name, value in original.items():
        assert getattr(action, name) == value
    assert payload == original


@pytest.mark.parametrize(
    "payload, error, message",
    [
        (None, TypeError, "mapping"),
        ([], TypeError, "mapping"),
        ({}, ValueError, "kind"),
        ({"kind": True}, TypeError, "kind"),
        ({"kind": ""}, ValueError, "unsupported"),
        ({"kind": "execute_shell"}, ValueError, "unsupported"),
    ],
)
def test_rejects_invalid_envelopes(payload, error, message):
    with pytest.raises(error, match=message):
        parse_agent_action(payload)


@pytest.mark.parametrize("kind", ["request_input", "call_tool", "finish"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_rejects_wrong_field_sets(kind, change):
    payload = make_payload(kind)
    if change == "missing":
        del payload["reason"]
    else:
        payload["status"] = "completed"

    with pytest.raises(ValueError, match="exactly"):
        parse_agent_action(payload)


@pytest.mark.parametrize(
    "kind, name, value, error",
    [
        ("request_input", "question", " ", ValueError),
        ("call_tool", "tool_name", True, TypeError),
        ("call_tool", "arguments", [], TypeError),
        ("call_tool", "arguments", {"limit": float("inf")}, ValueError),
        ("finish", "answer", " ", ValueError),
        ("finish", "reason", None, TypeError),
    ],
)
def test_preserves_validation_boundaries(kind, name, value, error):
    payload = make_payload(kind)
    payload[name] = value

    with pytest.raises(error):
        parse_agent_action(payload)


def test_parsed_tool_arguments_are_isolated():
    payload = make_payload("call_tool")

    action = parse_agent_action(payload)
    payload["arguments"]["limit"] = 99

    assert isinstance(action, CallToolAction)
    assert action.arguments["limit"] == 3
