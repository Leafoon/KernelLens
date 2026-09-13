# RUN-002A：补充信息行动与输入边界

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。最小 TaskState 已由用户实现并提交为 `1d0da40 feat: compose immutable task state`，开始本单元前工作区干净；当时应用验收为 72 个测试通过。
本单元定义第一种可执行意图：请求用户补充信息，并将外部映射校验为内部行动对象。用户实现已通过 Review、86 个测试及 lint/format，实际进度见 [当前能力与验证范围](status.md)。

## Concept

State 描述“现在是什么情况”，Action 描述“接下来提议做什么”。例如需求缺少目标设备，模型可以提议询问用户；提议被程序接受并处理后，任务才可能进入 WAITING_INPUT。
Action 不是执行结果，也不是给模型直接改写 TaskState 的权限。本轮创建行动对象不发送问题、不调用工具、不改变任务状态。

外部数据即使是字典，也可能缺字段、混入其他行动的参数，或者把 question 写成布尔值。Parser 的职责是检查结构与字段值，再构造明确的内部对象，避免后续代码反复猜测字典的含义。
这是接入 Structured Output 前的一段应用侧校验；尚未接入模型、JSON Schema 或任何供应商的结构化输出功能。

## Design

产品路径最终需要调用工具、请求信息和提交结果三类行动。本轮只实现请求信息这一类；其他行动到对应学习单元才添加，不创建空占位类。

示例输入：

```json
{
  "kind": "request_input",
  "question": "请提供目标 GPU 型号和输入 dtype。",
  "reason": "这两项信息会影响 GEMM 实现与测试方案。"
}
```

| 接口或字段 | 契约 |
| --- | --- |
| parse_request_input_action(payload) | 接受 Mapping，字段必须恰好为 kind、question、reason；返回 RequestInputAction |
| kind | 外部输入必须等于 request_input；内部对象固定为该值，构造时不接收覆盖参数 |
| question | 非空字符串，保留原文；给用户看的具体问题 |
| reason | 非空字符串，保留原文；说明为什么需要该信息，不要求模型内部思维链 |
| 非 Mapping、错误文本类型 | TypeError |
| 缺失／多余字段、错误 kind、空白文本 | ValueError |

控制流程见独立图源 [request-input-action.md](diagrams/request-input-action.md)。图中 Runtime 和进入等待状态是后续集成部分，本轮不实现。

重要边界：Parser 检查行动的形式，不判断问题是否必要、理由是否真实，也不处理重试。未知 kind 直接拒绝，不猜测为某个默认行动；未来总入口会根据 kind 分派到相应行动契约。
本轮 Parser 接收已经解码的映射，不接收 JSON 文本。后续模型适配层负责 JSON 解码、保留原始响应与报告解码错误，领域层不绑定供应商响应格式。

继续使用标准库。RequestInputAction 用 frozen dataclass；kind 的 Literal 标注只表达类型意图，实际约束来自 Parser、固定默认值与构造参数限制。
与一个只有 action_type 和任意 payload 的大字典相比，专用行动对象明确规定本行动必需的字段；工具参数与结果字段不会混在其中。

## Implementation

两个文件都由用户亲手创建。助手只保存讲义、专项图和项目文档。

### 文件一：src/kernellens/domain/action.py

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class RequestInputAction:
    question: str
    reason: str
    kind: Literal["request_input"] = field(default="request_input", init=False)

    def __post_init__(self) -> None:
        for name in ("question", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


def parse_request_input_action(payload: Mapping[str, object]) -> RequestInputAction:
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
    if not isinstance(reason, str):
        raise TypeError("reason must be a string")

    return RequestInputAction(
        question=question,
        reason=reason,
    )
```

按逻辑块理解：

1. Mapping 表达按键读取的数据接口，普通 dict 符合；函数无需修改输入，因此不要求输入一定是可变字典。object 表示字段值尚未验证，不假定它们都是字符串。
2. kind 是行动标签。Literal["request_input"] 表达这个标签只有一个预期值，但 Python 不会仅凭标注执行校验。field(..., init=False) 将它排除在构造参数之外；RequestInputAction(question=..., reason=...) 自动带上固定标签。
3. __post_init__ 检查 question 和 reason；先检查类型，再调用 strip。strip 只用于判空，不改写原文；直接构造对象也经过这些校验。
4. Parser 先检查外层 Mapping，再用 set(payload) 读取键集合。集合与顺序无关，要求恰好三个字段，同时拒绝缺字段与多余字段。
5. 结构确认后再按键读取，缺字段会得到我们定义的 ValueError，而不是意外的 KeyError。
6. 检查 kind 后显式传递两个字段，不能直接 RequestInputAction(**payload)：kind 不属于构造参数，而且这里需要明确外部输入到内部对象的转换。
7. 用户实现增加了局部变量及 isinstance 检查：将 Mapping 值的 object 类型缩窄为 str，使构造调用的参数类型明确。__post_init__ 仍校验类型与非空，因为其他调用者也可以绕过 Parser 直接构造对象；非空规则由构造函数统一负责。

参考代码已同步这个调整。类型缩窄帮助静态分析理解变量，运行时校验负责拒绝实际错误值，两者作用不同。本轮运行的是 pytest 和 Ruff，没有运行专门的静态类型检查器。返回对象仍是提议，没有执行副作用。

这不是完整的行动系统；CallToolAction、结果提交、Observation、Runtime 分派与状态更新仍未实现。

### 文件二：tests/test_action.py

```python
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
```

七个测试函数展开为 14 个用例：正常解析 1、缺字段 3、多余字段 1、其他 kind 2、非映射 2、错误文本 4、禁止重写 1。
make_payload 每次返回新字典，防止一个测试删字段影响另一个测试。它只是样例构造函数，不是测试目标，也不是模型替身。
这里不复制完整 TaskState 测试；Action 与 State 的集成行为留到 Runtime 单元。

## Run

保存后在项目根执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

参考实现的验收目标是 86 passed：已有 72 个，加上本单元 14 个。它不是当前已运行结果，实际验收见 docs/status.md。

## Observe

运行 `uv run --locked python`，逐行输入：

```python
from kernellens.domain.action import parse_request_input_action
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
state = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))
state = state.transition_to(TaskStatus.RUNNING)
payload = {
    "kind": "request_input",
    "question": "请提供目标 GPU 型号。",
    "reason": "需要据此选择实现与测试方案。",
}
action = parse_request_input_action(payload)
print(type(action).__name__, action.kind)
print(action.question)
print(state.status.value)
payload["tool_name"] = "read_source"
parse_request_input_action(payload)
```

三次打印预期为：

```text
RequestInputAction request_input
请提供目标 GPU 型号。
running
```

任务仍为 running，因为本轮只构造并校验行动，没有 Runtime 消费它。最后一行应抛出 `ValueError: action must contain exactly kind, question, and reason`，不能静默忽略混入的工具字段。
这个输入由你手写，不来自真实模型；本轮不会调用云端 API。使用 exit() 退出 Python。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 缺字段时报 KeyError | 堆栈先访问 payload["question"] | 字段集合校验遗漏或顺序错误 | 确认先检查结构，再读取字段 |
| 布尔值触发 AttributeError | 堆栈指向 strip | 先调用字符串方法再检查类型 | 将 isinstance 放到 strip 之前 |
| 多余工具字段被忽略 | DID NOT RAISE | 只取已知字段，没有拒绝额外字段 | 对照键集合的严格相等检查 |
| 正常解析提示 unexpected keyword argument 'kind' | 构造时用了 **payload | 外部字段被全部透传 | kind 是固定字段，显式传 question 和 reason |
| 测试之间互相影响 | 单跑通过、合跑失败 | 共用一个被修改的字典 | 每个测试调用 make_payload 获得新输入 |

先保留错误，按 Problem → Evidence → Hypothesis → Verification → Fix 定位；核心修复由用户完成。

## Checkpoint

本单元学习行动提议与状态的区别、结构化数据的应用侧校验、固定类型标签、显式边界转换和严格字段检查。
输入代码并运行、观察后回复“已完成”或“帮我检查”，助手读取实际文件 Review。通过验收后再保存 Git Checkpoint，建议 `feat: add validated request input action`，包含行动、测试、讲义、专项图及相关文档。
此时可验证的是一个具体行动契约与解析入口；不要把它记录成已实现 Tool Calling 或 Agent Runtime。本轮停在这个单元。
