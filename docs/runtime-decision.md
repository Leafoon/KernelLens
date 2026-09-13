# RUN-003A：一次模型决策与依赖注入

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。工具反馈契约已提交为
`a9588d2 feat: add tool observation contract`；进入本单元前工作区干净。
最近一次完整应用验收为 153 个测试及 lint/format 通过。

现在已有 TaskState、三种 AgentAction、统一 Parser 和 ToolObservation。
本单元把它们串成一次决策：接收运行中的任务和已有反馈，调用传入的模型函数，
校验返回值，得到下一步行动提议。完整循环会在后续单元建立。
实际进度见 [当前能力与验证范围](status.md)。

## Concept

**依赖注入（Dependency Injection）**：函数需要模型能力，但不在内部创建某个云端 SDK，
而是由调用者把可调用对象传进来。现在传入确定性的 fake_model，未来可传入模型适配器的方法。

它解决当前两个问题：我们能独立测试 Runtime 的调用边界；测试不依赖网络、密钥和随机回答。
如果直接在函数里创建 SDK，边界测试就会与外部服务耦合。当前一个函数参数已经足够，
不需要引入注入框架、抽象基类或完整 Provider 层。

FakeModel 是测试替身：返回我们指定的内容，用来观察程序如何处理结果。
它不会学习、推理或生成真实算子；这里的反馈样例也没有执行报告读取。

**一次决策与完整运行的区别**：decide_once 只负责取得一个合法行动提议。
谁执行工具、谁进入等待、何时接受 finish、如何限制循环，将由后续运行控制层负责。
这个层次遇到模型或解析异常时直接向调用者抛出，便于后续集中制定错误策略。

## Design

| 输入／输出 | 契约 | 用途 |
| --- | --- | --- |
| state | TaskState，且 status 必须为 RUNNING | 当前运行中的任务快照 |
| model | 可调用对象，签名由 DecisionModel 描述 | 接收 state 与 observations，返回已解码 Mapping |
| observations | ToolObservation 的 tuple，默认空 tuple | 把已有工具反馈传给决策函数 |
| 返回值 | AgentAction | 复用 parse_agent_action 校验的提议 |

专项图见 [一次决策流程](diagrams/runtime-decision.md)，在 VS Code 打开该 Markdown 文件即可预览。

控制顺序固定：检查本次输入 → 调用一次模型函数 → 解析响应 → 返回行动。
不允许 PENDING、WAITING_INPUT 或终态任务直接调用模型。后续调用者负责先显式转换到 RUNNING。

本轮用 tuple 表达只读的反馈序列，元素使用已定义的冻结 ToolObservation。
这让接收方不能直接 append 改写这份序列；它不是外部代码沙箱。
tuple 的合法类型不证明反馈属于这个任务、顺序正确或来源可信；执行标识和来源核验后续接入。
反馈也不会在这里自动合并进 TaskState.verification。

“调用一次”指 decide_once 调用传入对象一次，并不限制该对象内部的 SDK 重试、耗时或 Token。
本轮尚未提供完整运行预算、超时和上下文长度限制。

## Implementation

助手只创建 `src/kernellens/runtime/__init__.py` 包说明，并准备本文、图源与项目状态。
以下两个核心文件由用户亲手创建，不提前创建循环、工具执行器或模型适配器。

### 1. 单次决策函数

在 `src/kernellens/runtime/step.py` 输入：

```python
from collections.abc import Callable, Mapping

from kernellens.domain.action import AgentAction, parse_agent_action
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus

type DecisionModel = Callable[
    [TaskState, tuple[ToolObservation, ...]],
    Mapping[str, object],
]


def decide_once(
    state: TaskState,
    model: DecisionModel,
    observations: tuple[ToolObservation, ...] = (),
) -> AgentAction:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if state.status is not TaskStatus.RUNNING:
        raise ValueError("state must be running before a decision")
    if not callable(model):
        raise TypeError("model must be callable")
    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if any(not isinstance(item, ToolObservation) for item in observations):
        raise TypeError("observations must contain only ToolObservation values")

    payload = model(state, observations)
    return parse_agent_action(payload)
```

按逻辑块理解：

1. `DecisionModel` 是 Python 3.12 类型别名。Callable 的第一个部分描述两个参数，
   第二个部分描述返回的 Mapping；它只说明契约，不会自动验证返回值或调用函数。
2. `tuple[ToolObservation, ...]` 的省略号表示数量可变、元素类型相同；
   默认值 `()` 是不可变空元组。一个元素必须写作 `(observation,)`，逗号不可省略。
3. 五项输入检查都放在模型调用之前。无效状态和错误反馈不应该触发外部依赖。
   `callable(model)` 只能判断能否调用，不验证完整函数签名；签名错误会在调用时抛出。
4. `any(...)` 找出不符合 ToolObservation 类型的元素；空元组没有非法元素，允许首轮没有工具反馈。
5. 最后两行才产生依赖调用并校验返回值。函数不重复实现 Parser，也不捕获后假装成功。
   传入 `fake_model` 函数本身，而不是调用它得到的 `fake_model(...)` 返回值。
6. 返回 FinishAction 不会把 state 改为 COMPLETED；返回 RequestInputAction 也不会自动进入 WAITING_INPUT。
   状态转换属于下一层对行动的执行策略。

### 2. 调用边界测试

在 `tests/test_runtime_step.py` 输入下列测试。共 8 个测试函数，参数化后为 18 个用例。
这是同一个学习单元：测试我们刚刚设计的一次决策边界。

```python
import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING):
    return TaskState(
        request=TaskRequest(TaskType.DIAGNOSE, "说明报告读取情况"),
        status=status,
    )


def finish_payload():
    return {
        "kind": "finish",
        "answer": "当前只提交读取情况说明，未确认算子验证通过。",
        "reason": "提供本轮说明。",
    }


def must_not_run(state, observations):
    pytest.fail("model must not be called for invalid runtime input")


def test_calls_model_once_and_preserves_state():
    state = make_state()
    calls = []

    def fake_model(received_state, observations):
        calls.append((received_state, observations))
        return finish_payload()

    action = decide_once(state, fake_model)

    assert isinstance(action, FinishAction)
    assert action.answer == finish_payload()["answer"]
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] == ()
    assert state.status is TaskStatus.RUNNING


def test_passes_feedback_to_the_model():
    state = make_state()
    proposal = CallToolAction(
        tool_name="read_verification_report",
        arguments={"path": "reports/compile.json"},
        reason="读取回传报告。",
    )
    history = (
        ToolObservation(
            action=proposal,
            status=ToolExecutionStatus.FAILED,
            content="没有找到报告文件。",
        ),
    )
    calls = []

    def fake_model(received_state, observations):
        calls.append((received_state, observations))
        if observations[-1].status is ToolExecutionStatus.FAILED:
            return {
                "kind": "request_input",
                "question": "请确认报告文件路径。",
                "reason": "本轮没有取得报告。",
            }
        return finish_payload()

    action = decide_once(state, fake_model, observations=history)

    assert isinstance(action, RequestInputAction)
    assert action.question == "请确认报告文件路径。"
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] is history
    assert state.status is TaskStatus.RUNNING


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_rejects_non_running_tasks_before_calling_model(status):
    with pytest.raises(ValueError, match="running"):
        decide_once(make_state(status), must_not_run)


@pytest.mark.parametrize("state", [None, {}])
def test_rejects_invalid_state_before_calling_model(state):
    with pytest.raises(TypeError, match="state"):
        decide_once(state, must_not_run)


@pytest.mark.parametrize("observations", [None, [], (None,)])
def test_rejects_invalid_feedback_before_calling_model(observations):
    with pytest.raises(TypeError, match="observations"):
        decide_once(make_state(), must_not_run, observations=observations)


@pytest.mark.parametrize("model", [None, 42])
def test_rejects_non_callable_model(model):
    with pytest.raises(TypeError, match="callable"):
        decide_once(make_state(), model)


@pytest.mark.parametrize(
    "payload, error",
    [(None, TypeError), ({"kind": "unknown"}, ValueError)],
)
def test_rejects_invalid_model_output_without_retry(payload, error):
    calls = []

    def fake_model(state, observations):
        calls.append(state)
        return payload

    with pytest.raises(error):
        decide_once(make_state(), fake_model)
    assert len(calls) == 1


def test_model_exception_propagates_without_retry():
    calls = []

    def failing_model(state, observations):
        calls.append(state)
        raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        decide_once(make_state(), failing_model)
    assert len(calls) == 1
```

测试中的三个关键技巧：

- `calls` 列表记录替身的实际调用，是简易 spy；断言调用次数和输入对象，验证行为。
- `must_not_run` 被误调用就立即使测试失败，证明非法输入在模型调用之前被拒绝。
- 工具失败反馈让替身返回请求信息提议，验证反馈确实传入；这是手写规则，不是模型智能或真实 Re-planning 的评测。

已有 Parser 测试负责三种输出的详细字段校验；本单元检查 Runtime 是否实际使用该入口，
以及异常发生后有没有意外重试。使用局部替身即可，出现跨文件复用后再抽取公共测试工具。

## Run

在本项目根目录执行：

```bash
uv run --locked pytest -q tests/test_runtime_step.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

新测试预期 **18 passed**；lint/format 应通过。完整回归命令为
`uv run --locked pytest -q`，本单元全部正确且没有其他改动时预期 **171 passed**。
这些是目标结果；用户尚未输入代码时，不能把参考代码检查当作应用测试通过。

## Observe

实现后在项目根目录把下面整段作为终端命令运行。Shell 的引号 heredoc 把内部内容原样交给 Python，
不需要新增演示脚本或连接服务器。

```bash
uv run --locked python - <<'PY'
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.step import decide_once

calls = []


def fake_model(state, observations):
    calls.append((state, observations))
    return {
        "kind": "request_input",
        "question": "请提供服务器报告路径。",
        "reason": "当前缺少报告。",
    }


state = TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断 GEMM 编译失败"))
try:
    decide_once(state, fake_model)
except ValueError as error:
    print(error)
print(len(calls))

state = state.transition_to(TaskStatus.RUNNING)
action = decide_once(state, fake_model)
print(action.kind)
print(state.status.value)
print(len(calls))
PY
```

预期依次输出：

```text
state must be running before a decision
0
request_input
running
1
```

先解释再对照：

- 初始 PENDING 被拒绝，模型调用次数仍为 0。
- 接收 transition_to 返回的新 RUNNING 快照后，才允许决策。
- 解析后得到 request_input 行动，但 state 仍为 running。
- 替身只被调用一次；没有真实模型请求、工具执行或用户消息发送。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入 decide_once | ModuleNotFoundError 或 ImportError | 文件位置、保存或函数作用域有误 | 核对 runtime/step.py，函数与别名顶格定义 |
| 第一次决策报 running 错误 | state.status 为 PENDING | 调用前没有进入运行态 | 用 transition_to 并接收新快照；保留当前入口校验 |
| 模型参数报 callable 错误 | 传入的是字典 | 写成了 fake_model(...) | 传函数本身，让 decide_once 控制何时调用 |
| 一个反馈被拒绝 | observations 不是 tuple | 写成了 (observation) | 使用 (observation,)；列表同样会被明确拒绝 |
| must_not_run 触发失败 | pytest 显示模型意外调用 | 把检查放在调用之后或漏掉检查 | 先看失败用例对应字段，再调整检查顺序 |
| 返回字典触发 Parser 错误 | 报 kind 或字段集合错误 | 替身没有遵循已有行动契约 | 对照 action.py 的精确标签与字段，修正返回值 |
| 模型异常向外抛出 | RuntimeError，调用次数为 1 | 本层尚未负责重试或生命周期失败处理 | 对照契约与测试；不要吞掉异常或伪造 finish |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。

## Checkpoint

本单元完成后应理解：如何把模型当作可替换依赖，如何让前置检查阻止无效调用，
如何把反馈传回决策入口，以及为什么解析、执行和状态转换要有各自的责任。

用户实现已通过 Review：171 个测试（含本单元 18 个用例）、lint/format 与运行观察通过。
助手仅整理导入名称顺序、空行与末尾换行；核心逻辑与测试由用户完成。
实际观察为：PENDING 不调用替身；RUNNING 得到 request_input 后状态仍为 running，调用次数为 1。

已由用户提交为 `403c05b feat: add validated runtime decision step`，
包含一次决策函数、行为测试、包入口与配套文档；实际提交及干净工作区已核对。
本单元未接入预算或循环。当前进度见 [当前能力与验证范围](status.md)。
