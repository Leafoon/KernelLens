# RUN-002B：工具调用提议与参数快照

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。补充信息行动已提交为 `ce48217 feat: add validated request input action`；开始本单元前工作区干净，当时应用验收为 86 个测试通过。
本单元定义 CallToolAction，重点学习参数所有权与只读快照。用户实现已通过 Review、105 个测试及 lint/format；实际进度见 [当前能力与验证范围](status.md)。

## Concept

工具调用提议回答三个问题：调用哪个工具、传什么参数、为什么调用。例如为了查找 GEMM 的源码依据，可以提议 search_source，并传入关键词和返回数量上限。
本轮的 search_source 是拟议工具名；创建行动不会搜索源码，也不证明这个工具已经存在。

新问题在于参数是容器：frozen=True 阻止给 action.arguments 重新赋值，却不能自动阻止 action.arguments["limit"] = 99。
如果行动直接保存调用者的字典，调用者后来改了字典，提议中的参数也会改变。这会让后续观察、审阅和执行无法对应同一份内容。

| 方案 | 能解决什么 | 剩余问题 |
| --- | --- | --- |
| frozen dataclass 保存原字典 | 阻止常规字段重新赋值 | 原字典与内部参数仍可被修改 |
| 复制字典 | 隔离调用者对原字典的修改 | 行动持有的副本仍可被写入 |
| 复制后提供只读视图 | 隔离原输入，并拒绝通过视图写入 | 嵌套可变值仍需另行处理 |

本轮选择第三种，并明确限制参数值为不可变标量。这样已有工具提议能保存稳定的参数，不需要现在实现递归容器冻结。

## Design

| 字段 | 契约 |
| --- | --- |
| tool_name | 非空字符串，保留原文；工具注册名称，不是待执行的 Python 表达式 |
| arguments | 必须提供 Mapping；允许空映射；键为非空字符串 |
| arguments 的值 | 只接受 str、int、有限 float、bool、None；本轮拒绝列表、字典及其他对象 |
| reason | 非空字符串，保留原文；简短说明本次调用的目的 |
| kind | 固定 call_tool，不接受构造参数覆盖 |

初期计划的源码检索／片段读取参数是关键词、路径、行号、数量上限等，平坦标量映射足以表达第一版提议。
这是本单元的明确边界，并非声称所有工具参数都只能是标量。真实工具需要 shape 数组或嵌套配置时，再扩展参数契约与相应测试；当前不静默接收无法保护的容器。
NaN 和 Infinity 被拒绝，因为它们不是标准 JSON 数值；保持参数适合后续 JSON 传输。此处不验证具体工具是否允许 None、负数或某个参数名，这属于之后的工具 Schema。

接口为 `CallToolAction(tool_name=..., arguments=..., reason=...)`，输出持有独立只读参数快照的对象。
非字符串文本、非 Mapping、非字符串键、不支持的参数值抛 TypeError；空白文本／键和非有限浮点数抛 ValueError。

流程图见独立图源 [tool-call-action.md](diagrams/tool-call-action.md)。通用行动解析、工具是否注册、参数 Schema、权限、调用标识、工具版本及执行留到对应单元。
本轮保留现有 parse_request_input_action，只支持补充信息行动；不让它兼任工具调用解析器。

## Implementation

核心类和测试由用户输入。只改已有 action.py，并新增一个测试文件，不创建 Runtime、Registry 或工具实现。

### 文件一：修改 src/kernellens/domain/action.py

将文件顶部导入整理为：

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal
```

保留现有 RequestInputAction 和 parse_request_input_action，在文件末尾追加：

```python
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
```

按逻辑块理解：

1. tool_name 与 reason 复用已经掌握的非空文本契约；kind 是固定行动标签。
2. arguments 显式必填，空字典可以表示无参数调用；工具是否真的不需要参数，之后由其 Schema 判断。
3. dict(self.arguments) 创建行动自己持有的副本，再验证这个副本。它是浅拷贝，但本轮只允许不可变标量，不存在需要递归复制的列表／字典。
4. bool 单独列出是为了表达支持的参数语义；Python 中 bool 也是 int 的子类，这里并不区分某工具是否允许布尔值作为整数参数。精确字段类型由工具 Schema 负责。
5. isfinite 排除 NaN、正负 Infinity。错误保留参数名，便于定位是哪一个值不合约。
6. MappingProxyType 是只读视图，本身不会复制底层字典；因此要包裹刚刚创建的副本，不能直接包裹调用者的原字典。
7. object.__setattr__ 用于构造期间把输入替换为已经校验的只读快照。之后普通字段赋值由 frozen 阻止，通过视图修改参数由 MappingProxyType 阻止。不要在正常更新路径使用它绕过快照规则。

这属于领域数据约束，不是阻止任意 Python 代码破坏对象的安全沙箱。输出映射需要普通字典时显式使用 dict(action.arguments)，例如交给后续 JSON 编码；不承诺 MappingProxyType 可以直接被 json.dumps 或 dataclasses.asdict 处理。

### 文件二：新建 tests/test_tool_call_action.py

```python
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
```

10 个测试函数展开为 19 个用例。重点是参数快照的可观察行为，不检查私有变量或强制某个具体内部类型。
测试中的非法赋值与错误类型是故意构造的失败场景；编辑器可能指出它们不符合类型约定，pytest 则验证运行时是否正确拒绝。

## Run

保存后在项目根执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

参考实现的验收目标为 105 passed：已有 86 个，加上本单元 19 个。这是实现后的目标，实际验收以 docs/status.md 为准。

## Observe

运行 uv run --locked python，逐行输入：

```python
from kernellens.domain.action import CallToolAction
original = {"query": "T.gemm", "limit": 3}
action = CallToolAction("search_source", original, "查找 GEMM 的源码依据。")
original["limit"] = 99
print(original["limit"], action.arguments["limit"])
print(action.kind)
action.arguments["limit"] = 10
print(action.arguments["limit"])
```

前两次打印应为 `99 3` 和 `call_tool`。赋值行动参数时应抛 TypeError；交互解释器中继续输入最后一行，仍为 3。
这说明修改输入不会改写提议，调用者也不能通过公开映射修改参数。用 exit() 退出；没有任何工具真正被执行。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 原输入修改后提议也变了 | 快照隔离测试失败 | 只给原字典套了只读视图 | 确认先 dict 复制，再创建 MappingProxyType |
| 能直接修改行动参数 | DID NOT RAISE | 只有 frozen 或只复制字典 | 检查副本是否通过只读视图保存 |
| 构造时 FrozenInstanceError | 堆栈在 self.arguments = ... | 构造规范化使用普通赋值 | 对照构造期间的 object.__setattr__ |
| 嵌套列表被接受 | scalar 测试失败 | 把浅拷贝误当深层保护 | 保持当前标量边界，容器支持另行设计 |
| NaN 被接受 | finite 测试失败 | 只检查 float 类型 | 增加 isfinite 检查，不修改预期 |

按照 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心逻辑由用户修改。

## Checkpoint

本单元学习工具调用提议、参数所有权、frozen 的边界、浅拷贝与只读视图，以及通用契约和具体工具 Schema 的分工。
输入代码并运行、观察后回复“已完成”或“帮我检查”。验收后建议 `feat: add tool call action with argument snapshots`，包含行动、测试、讲义、专项图和相关文档；提交对应可独立验证的提议与参数快照功能。
本轮不实现通用行动解析、Registry、工具执行、模型调用或 Runtime；不能把 CallToolAction 已定义记录为 Tool Calling 已运行。
