from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction


def make_action(arguments):
    return CallToolAction(
        tool_name="search_source",
        arguments=arguments,
        reason="查找 GEMM 的源码依据。",
    )


def test_preserves_scalar_arguments():
    arguments = {
        "query": "T.gemm",
        "limit": 3,
        "threshold": 0.5,
        "include_docs": True,
        "device": None,
    }
    action = make_action(arguments)

    assert action.kind == "call_tool"
    assert action.tool_name == "search_source"
    assert action.reason == "查找 GEMM 的源码依据。"
    assert dict(action.arguments) == arguments


def test_allows_empty_arguments():
    assert dict(make_action({}).arguments) == {}


def test_input_changes_do_not_rewrite_proposal():
    original = {"query": "T.gemm", "limit": 3}
    action = make_action(original)

    original["limit"] = 99
    original["extra"] = True

    assert dict(action.arguments) == {"query": "T.gemm", "limit": 3}


def test_arguments_are_read_only():
    action = make_action({"limit": 3})

    with pytest.raises(TypeError):
        action.arguments["limit"] = 99

    assert action.arguments["limit"] == 3


@pytest.mark.parametrize(
    "name, value, error",
    [
        ("tool_name", True, TypeError),
        ("tool_name", " \t ", ValueError),
        ("reason", None, TypeError),
        ("reason", "", ValueError),
    ],
)
def test_rejects_invalid_text(name, value, error):
    inputs = {"tool_name": "search_source", "arguments": {}, "reason": "查找依据。"}
    inputs[name] = value

    with pytest.raises(error, match=name):
        CallToolAction(**inputs)


@pytest.mark.parametrize("arguments", [None, [], "{}"])
def test_rejects_non_mapping_arguments(arguments):
    with pytest.raises(TypeError, match="arguments"):
        make_action(arguments)


@pytest.mark.parametrize("name, error", [(3, TypeError), ("  ", ValueError)])
def test_rejects_invalid_argument_names(name, error):
    with pytest.raises(error, match="argument names"):
        make_action({name: "value"})


@pytest.mark.parametrize("value", [["T.gemm"], {"query": "T.gemm"}])
def test_rejects_nested_containers(value):
    with pytest.raises(TypeError, match="scalar"):
        make_action({"query": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError, match="finite"):
        make_action({"threshold": value})


def test_arguments_field_cannot_be_reassigned():
    action = make_action({"limit": 3})

    with pytest.raises(FrozenInstanceError):
        action.arguments = {}
