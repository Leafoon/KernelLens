from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal


# frozen=True 表示对象创建后不能再修改字段
@dataclass(frozen=True)
class RequestInputAction:
    question: str  # 要向用户提出的问题
    reason: str  # 为什么需要向用户询问这个问题

    kind: Literal["request_input"] = field(
        default="request_input",
        init=False,
    )

    # dataclass 完成 __init__ 后会自动调用 __post_init__
    def __post_init__(self) -> None:

        for name in ("question", "reason"):
            value = getattr(self, name)

            # question 和 reason 必须是字符串
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


def parse_request_input_action(
    payload: Mapping[str, object],
) -> RequestInputAction:
    """
    将外部传入的 Mapping 数据解析并校验为 RequestInputAction。

    例如输入：

    {
        "kind": "request_input",
        "question": "你使用什么 GPU？",
        "reason": "需要确定目标架构",
    }

    校验成功后返回 RequestInputAction 对象。
    """
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    if set(payload) != {"kind", "question", "reason"}:
        raise ValueError("action must contain exactly kind, question, and reason")
    if payload["kind"] != "request_input":
        raise ValueError("expected request_input action")

    question = payload["question"]
    reason = payload["reason"]

    if not isinstance(question, str):
        raise TypeError("question must be a string")

    # 同样，把 reason 从 object 缩窄为 str
    if not isinstance(reason, str):
        raise TypeError("reason must be a string")

    return RequestInputAction(
        question=question,
        reason=reason,
    )


@dataclass(frozen=True)
class CallToolAction:
    tool_name: str
    arguments: Mapping[str, object]
    reason: str
    kind: Literal["call_tool"] = field(default="call_tool", init=False)

    def __post_init__(self) -> None:
        for name in ("tool_name", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")

        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")

        snapshot = dict(self.arguments)

        for name, value in snapshot.items():
            if not isinstance(name, str):
                raise TypeError("argument names must be strings")
            if not name.strip():
                raise ValueError("argument names must not be blank")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise TypeError(f"argument {name!r} must be a scalar")
            if isinstance(value, float) and not isfinite(value):
                raise ValueError(f"argument {name!r} must be finite")

        object.__setattr__(self, "arguments", MappingProxyType(snapshot))


@dataclass(frozen=True)
class FinishAction:
    answer: str
    reason: str
    kind: Literal["finish"] = field(default="finish", init=False)

    def __post_init__(self) -> None:
        for name in ("answer", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


type AgentAction = RequestInputAction | CallToolAction | FinishAction


def parse_agent_action(payload: Mapping[str, object]) -> AgentAction:
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    if "kind" not in payload:
        raise ValueError("action must contain kind")

    kind = payload["kind"]
    if not isinstance(kind, str):
        raise TypeError("kind must be a string")

    if kind == "request_input":
        return parse_request_input_action(payload)

    if kind == "call_tool":
        expected = {"kind", "tool_name", "arguments", "reason"}
        if set(payload) != expected:
            raise ValueError("call_tool must contain exactly its required fields")

        tool_name = payload["tool_name"]
        arguments = payload["arguments"]
        reason = payload["reason"]
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string")
        if not isinstance(arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        if not isinstance(reason, str):
            raise TypeError("reason must be a string")

        return CallToolAction(tool_name=tool_name, arguments=arguments, reason=reason)

    if kind == "finish":
        expected = {"kind", "answer", "reason"}
        if set(payload) != expected:
            raise ValueError("finish must contain exactly its required fields")

        answer = payload["answer"]
        reason = payload["reason"]
        if not isinstance(answer, str):
            raise TypeError("answer must be a string")
        if not isinstance(reason, str):
            raise TypeError("reason must be a string")

        return FinishAction(answer=answer, reason=reason)

    raise ValueError(f"unsupported action kind: {kind!r}")
