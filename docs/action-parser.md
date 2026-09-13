# RUN-002D：统一行动解析入口

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。三种行动契约已由用户实现并提交：
`42f0216 feat: add finish action and agent action union`。进入本单元前工作区干净；
本单元开始时的验收基线为 115 个测试与 lint/format 通过。

本单元开始时只有 parse_request_input_action 能解析外部映射。联合类型只声明允许的返回类型，
不会把字典变成对象。本单元增加 parse_agent_action 作为三类行动的统一输入入口。
助手只准备讲义、图源和状态文档；核心实现与测试由用户输入，真实状态见 [当前能力与验证范围](status.md)。

## Concept

**分派（dispatch）**是按明确规则选择处理路径。这里由程序读取 kind，精确选择对应的行动解析逻辑；
这是确定性的协议分派，不是让模型重新决定该做什么。

一个完整边界分三层：

1. 外层映射和标签是否合法，由统一 Parser 检查。
2. 对应行动是否恰好具有规定字段，由该分支检查。
3. 字段值是否满足对象不变量，由已有构造函数继续保证。

Parser 返回的只是结构合法的提议。工具是否存在、是否获准执行、答案是否有依据，
属于后续 Registry、Runtime 与业务验收。返回 FinishAction 不会自动完成任务。

## Design

| 输入 kind | 必须恰好包含的字段 | 返回类型 |
| --- | --- | --- |
| request_input | kind、question、reason | RequestInputAction |
| call_tool | kind、tool_name、arguments、reason | CallToolAction |
| finish | kind、answer、reason | FinishAction |

接口：`parse_agent_action(payload: Mapping[str, object]) -> AgentAction`。

- 输入必须是已解码映射；JSON 字符串和列表不在当前接口范围。
- 非映射抛 TypeError；缺少 kind 抛 ValueError；kind 不是字符串抛 TypeError。
- kind 只接受上述三个精确值；空串、拼写错误、大小写变化或未知值抛 ValueError，不提供默认行动。
- 已知行动先检查字段集合，再提取字段；缺字段、多字段均拒绝，避免错把另一类行动解释成当前类。
- 显式 isinstance 检查将局部 object 缩窄为字符串或 Mapping；非空文本、标量参数、有限浮点数和参数快照继续复用构造函数。
- 不删除或修改调用者 payload 的字段。对工具参数的隔离仍由 CallToolAction 负责。
- 不捕获后自动重试、不执行工具、不更新 TaskState。统一 Parser 的公共错误行为单独定义，
  现有 parse_request_input_action 的接口与错误顺序保持原样。

三个确定分支足够清晰，暂不引入解析器注册表、反射或新增依赖。程序分派与工具注册解决不同问题。
流程见独立图源 [action-parser.md](diagrams/action-parser.md)。

## Implementation

### 文件一：修改 src/kernellens/domain/action.py

保留全部已有代码和导入。在模块级 `type AgentAction = ...` **之后**追加下面一个函数。
def 行顶格，和 type、class 同级，不要放进任何类或其他函数中。

```python
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
```

按逻辑块理解：

1. 前两个 if 保证能安全读取 kind；随后验证标签类型。缺少字段与字段值类型错误分别报告。
2. request_input 分支调用既有 Parser，已有直接调用路径及其测试继续有效。
3. call_tool 分支先验证四个字段，再缩窄三个局部变量类型，将最终字段约束与参数复制交给 CallToolAction。
4. finish 分支先验证三个字段，再交给 FinishAction。这里没有任务状态参数。
5. 最后一条 raise 拒绝未知标签。不能把未知值默认为 finish，也不能返回 None。
6. 每个成功分支 return 一个对象；返回类型用 AgentAction 描述。外部字典的校验靠上述代码执行，
   不靠返回类型注解执行。

### 文件二：新建 tests/test_action_parser.py

下面是本单元完整测试参考。按顺序输入，包含完整导入块；不要覆盖已有的 test_finish_action.py。

```python
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
```

make_payload 只生成手写测试输入，每次调用创建新的字典；search_source 是测试用工具名，当前没有注册或执行该工具。

测试用途：

- 三类正常输入验证返回的具体对象、全部字段与输入保留；deepcopy 保存包含嵌套 arguments 的原始样例，
  避免比较时原始样例也被修改而掩盖问题。deepcopy 只用于这里的测试，不改变生产快照策略。
- 错误外层与标签用例验证入口契约，尤其覆盖未知标签不能意外变成完成提议。
- 缺少 reason 和额外 status 用例覆盖三个分支的字段集合边界。
- 无效字段用例验证统一入口继续执行既有类型、空白文本和非有限数值约束。
- 参数隔离用例确认外部字典后续修改不会改写已解析的工具提议。

5 个测试函数展开为 22 个用例：3 + 6 + 6 + 6 + 1。
这不是完整安全测试集或 Agent Evaluation；后续新接口与发现的问题会增加回归用例。

## Run

先保存源码和新测试文件，再在项目根执行：

```bash
uv run --locked pytest -q tests/test_action_parser.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期专项为 22 passed；本单元全量测试为 137 个（原有 115 + 新增 22）。
用户实现已验收，全量实测 137 passed，lint/format 通过；最新记录见 docs/status.md。若后续仅排版不符，格式化提示的文件后重新检查。

## Observe

运行 `uv run --locked python` 后输入：

```python
from kernellens.domain.action import parse_agent_action

payload = {
    "kind": "call_tool",
    "tool_name": "search_source",
    "arguments": {"query": "gemm", "limit": 3},
    "reason": "寻找源码依据。",
}
action = parse_agent_action(payload)
payload["arguments"]["limit"] = 99
print(type(action).__name__)
print(dict(action.arguments))
print(payload["arguments"])
```

预期：CallToolAction；提议参数 limit 仍为 3；输入参数 limit 已为 99。
这表示完成了解析和参数隔离，未执行 search_source。

继续输入：

```python
parse_agent_action({"kind": "execute_shell"})
```

预期 ValueError，包含 unsupported action kind。拒绝是正常的边界行为，
不会产生默认行动或执行命令。用 exit() 退出 Python。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 新函数无法导入 | ImportError 指向 parse_agent_action | 未保存、名称不一致或作用域错误 | 确认 def 在 action.py 模块顶层，保留既有别名和导入 |
| 缺字段时抛 KeyError | 错误指向 payload 下标 | 在字段集合检查前取值 | 先检查 kind 存在，再按分支检查完整字段集合 |
| 未知标签返回 None 或成功对象 | 未拒绝 execute_shell | 遗漏末尾 raise 或设置了默认分支 | 明确抛出 ValueError |
| 非法工具参数被接受 | 非有限值用例未抛错 | 绕过了已有 CallToolAction 构造校验 | 返回构造完成的领域对象，不直接返回字典 |
| 提议参数随原输入变化 | action.arguments 的 limit 变成 99 | 参数快照被绕过 | 沿解析分支定位是否复用了现有 CallToolAction |
| 测试自身 NameError | 错误发生在断言准备处 | 遗漏导入或名称拼错 | 先核对完整导入，再判断被测逻辑；不要修改期望让测试勉强通过 |

按 Problem → Evidence → Hypothesis → Verification → Fix 排错。本轮核心修复仍由用户完成。

## Checkpoint

本单元目标：把外部结构数据校验并转换成三种行动对象，理解协议分派、字段集合校验、
类型缩窄和构造函数不变量的配合，以及解析和执行的职责边界。

用户实现已通过 Review：137 个测试、lint/format 与运行观察通过；已提交为 `234282f feat: add validated agent action parser`，包括函数、测试、本讲义、专项图与相关状态文档。当前进度见 [当前能力与验证范围](status.md)。
本轮不实现 Observation、工具执行器、模型调用或 Runtime。
