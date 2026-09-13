# RUN-003E：执行工具行动并校验反馈归属

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前处于 Phase 2 — State & Minimal Runtime。
RUN-003D 已提交为 `4b8cdff feat: gate task completion on finish review`，进入本单元前工作区干净。
进入本单元前的完整验收为 229 个测试及 lint/format、运行观察通过。

目前已有单次决策、决策额度、请求信息处理和完成审核。
本单元让 CallToolAction 经过程序侧执行函数，返回可交给下一次决策的 ToolObservation。
只完成这一条调用边界；工具注册、真实文件读取、预算集成和完整循环在后续单元实现。

## Concept

**提议、执行、观察。** CallToolAction 只表达工具名、参数和理由。
ToolExecutor 是程序注入的可调用接口，接受一条行动并返回反馈；ToolObservation 保存执行结果。
本步调用测试替身，因此不会读取 report.json、执行算子或发起模型请求。

**反馈必须对应当前行动。** 若读取 A 报告却收到另一条行动的结果，下一次决策可能基于错误材料。
本进程内用 `observation.action is action` 检查是否保留原 Action 对象。
`==` 比较字段内容；两个不同对象可以字段完全相同，不能用它证明引用一致。
这个约定要求执行函数构造 ToolObservation 时直接传入收到的 action。
它只建立对象关联：同一个 Action 被重复执行时仍不能区分尝试，也不认证反馈来源或内容。
跨进程、Provider 协议和重试需要的 call ID / attempt ID 后续按需求设计。

**两种失败要分开。**

| 情况 | 当前处理 | 下一层能够知道什么 |
| --- | --- | --- |
| 执行函数正常返回 SUCCEEDED / FAILED 反馈 | 校验后原样返回 | 得到了可观察的工具结果，包括工具失败 |
| 执行函数抛出异常 | 原异常传播，不重试 | 此次调用没有正常返回反馈 |
| 返回值类型错误或反馈关联错误 | 抛 TypeError / ValueError | 程序接口契约不满足，不能交给模型当作本次结果 |

例如找不到报告，可以由将来的工具适配器归一为 FAILED 反馈；未知程序错误不能一律吞掉后伪装成工具成功。
FAILED 反馈不自动把任务改成 FAILED：后续仍可能请求正确路径或选择其他工具。
错误反馈进入下一次决策也不等于已实现恢复策略，本单元只验证它能被传递。
一次有效 Handler 调用只调用 executor 一次；若它内部另行重试，本层并不能统计或阻止。
异常传播也不会撤销外部已发生的副作用，当前不自动重试。

**为什么选一个普通函数接口？** Runtime 需要调用能力，但现在还没有真实工具注册和路由。
直接在 Handler 中塞入读文件逻辑会使它绑定具体工具。
注入一个函数就能独立测试输入、反馈和失败边界，后续可接入正式执行器；当前不需要新框架、服务或依赖。

## Design

| 项目 | 契约 |
| --- | --- |
| 输入 state | TaskState，且 status 为 RUNNING |
| 输入 action | CallToolAction |
| 关键字参数 executor | ToolExecutor = Callable[[CallToolAction], ToolObservation]，无默认值 |
| 输出 | 原 ToolObservation 对象，必须关联输入的原 Action 对象 |
| 前置失败 | TypeError / ValueError，不调用 executor |
| 后置失败 | TypeError / ValueError，不把无效反馈返回给调用者 |
| 执行异常 | 原异常传播；当前 Handler 不重试、不更新生命周期 |
| State / 检查结果 | 不修改；也不合并 observation.verification |

流程图见 [工具执行与反馈校验](diagrams/tool-call-handler.md)，可在 VS Code 独立预览。

控制顺序：检查状态类型 → 检查 RUNNING → 检查行动类型和 executor →
调用一次 → 检查 ToolObservation 类型 → 检查 Action 引用 → 返回反馈。

这里不调用 transition_to(RUNNING)：任务原本就处于 RUNNING，而现有状态机拒绝同状态转换。
本函数的产出是反馈，所以返回 ToolObservation；调用者继续持有原状态。
反馈携带的报告还没有候选、来源和环境核对，不能直接覆盖任务累计验证结果。
下一次决策需要调用者显式传入 `(observation,)`；本步不保存历史、不消费预算。

## Implementation

核心扩展和测试由你输入。本单元只修改一个已有源码文件、创建一个测试文件。

### 1. 扩展 handlers.py

文件：`src/kernellens/runtime/handlers.py`。
先把文件顶部的 import 区域整理为下面的形式；下方已有类型别名、异常类和两个 Handler 均保留。

```python
from collections.abc import Callable

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState, TaskStatus, transition_status
```

在模块顶层、现有 FinishReviewer 类型别名的下一行添加：

```python
type ToolExecutor = Callable[[CallToolAction], ToolObservation]
```

在 apply_finish 后追加函数，两个顶层函数之间保留两行空行：

```python
def apply_call_tool(
    state: TaskState,
    action: CallToolAction,
    *,
    executor: ToolExecutor,
) -> ToolObservation:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if state.status is not TaskStatus.RUNNING:
        raise ValueError("state must be running before tool execution")
    if not isinstance(action, CallToolAction):
        raise TypeError("action must be a CallToolAction")
    if not callable(executor):
        raise TypeError("executor must be callable")

    observation = executor(action)
    if not isinstance(observation, ToolObservation):
        raise TypeError("executor must return a ToolObservation")
    if observation.action is not action:
        raise ValueError("observation must reference the original action")
    return observation
```

按逻辑块理解：

- 前置检查保护调用边界。非 RUNNING 状态不允许工具继续执行，规则与 decide_once 保持一致。
- `executor=...` 是必须显式指定的关键字参数，程序负责提供执行依赖。
- `executor(action)` 传递原对象；测试通过调用记录检查是否只调用一次。
- 返回后先查类型，再访问 action 字段，避免把错误返回当成合法 Observation。
- `is not` 关注对象身份；类型和字段相同仍可能是另一条行动。
- 最后原样返回反馈，包括 FAILED；这里不改变任务状态或推断检查通过。

### 2. 创建工具行动处理测试

文件：`tests/test_tool_call_handler.py`。共 9 个测试函数，参数化后 27 个用例。

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
```

| 测试组 | 用例数 | 验证目的 |
| --- | ---: | --- |
| 三种任务 × 两种工具状态 | 6 | 原样返回反馈，调用一次，不合并报告或改变状态 |
| 六种非运行态 | 6 | 状态检查在调用之前 |
| 非法 state | 2 | 类型边界 |
| 其他行动或非法值 | 4 | 只执行工具行动 |
| 非可调用 executor | 2 | 依赖检查 |
| 错误返回类型 | 3 | 拒绝未满足反馈契约的对象 |
| 同内容的新行动 / 不同工具行动 | 2 | 字段相等也不能替代原对象关联 |
| 执行函数异常 | 1 | 异常传播，不重试、不改变生命周期 |
| 失败反馈传给下一次决策 | 1 | 验证手工连接后的反馈路径 |

测试中的 compilation=FAILED 是手写数据；它和工具状态是两个独立维度。
最后一个测试的 model 根据预设返回 request_input，只证明反馈可传入，没有真实模型推理或自动恢复。
尚未审核任何真实报告。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_tool_call_handler.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

2026-09-10 已对用户实现运行完整回归：**256 passed in 0.09s**，包含本文件的 **27 个新增用例**。
实际命令为 `uv run --locked --offline --no-cache --no-python-downloads pytest -q`；Ruff lint 与 format 检查通过，共 27 个 Python 文件。
助手仅整理 handlers.py 的 import 区域末尾、函数间和文件末尾空行，语法树及去除空白后的文本不变；未修改核心逻辑或测试。

## Observe

实现后，在项目根目录运行整段命令：

```bash
uv run --locked python - <<'PY'
from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.handlers import apply_call_tool
from kernellens.runtime.step import decide_once


def execute(action):
    return ToolObservation(action, ToolExecutionStatus.FAILED, "报告文件不存在。")


def model(state, observations):
    print(observations[-1].content)
    return {
        "kind": "request_input",
        "question": "请提供正确的报告路径。",
        "reason": "读取报告失败，需要补充信息。",
    }


state = TaskState(TaskRequest(TaskType.DIAGNOSE, "读取 GEMM 报告"))
state = state.transition_to(TaskStatus.RUNNING)
action = CallToolAction(
    tool_name="read_report",
    arguments={"path": "report.json"},
    reason="检查服务器执行结果。",
)
observation = apply_call_tool(state, action, executor=execute)
print(observation.status.value)
print(observation.action is action)
print(state.status.value)
next_action = decide_once(state, model, (observation,))
print(next_action.kind)
print(state.verification.compilation.value)
PY
```

实际本地替身观察输出（2026-09-10）：

```text
failed
True
running
报告文件不存在。
request_input
not_run
```

执行函数返回失败反馈，Action 仍是原对象，任务继续保持 running。
下一次决策收到这份反馈并提出补充信息行动；compilation 仍为 not_run。
注意这里只调用了 decide_once，尚未应用新行动，因此不会自动进入 waiting_input。
这个示例中的两个依赖都是普通本地函数，不读取文件、不调用 API。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 停止态仍触发工具 | must_not_run 失败 | 执行放在状态检查前 | 先检查 RUNNING，再调用 executor |
| 返回字典后属性访问报错 | 错误返回类型测试失败 | 先访问 action 后查类型 | 先 isinstance，再查关联 |
| 同内容新对象被接受 | original action 测试失败 | 用了 == / != 比较 | 检查对象身份，使用 is / is not |
| 合法反馈被判成另一条行动 | ValueError | 执行函数重建了 Action | ToolObservation 使用收到的原 action |
| 工具失败后任务变为 FAILED | 状态断言失败 | 混淆工具结果与生命周期 | 原样返回反馈，留给后续流程处理 |
| 第二次决策没看到反馈 | 组合测试失败 | 没传 tuple 或丢了 observation | 显式传入 (observation,)；单元素 tuple 需要逗号 |
| 执行异常被吞掉或重复调用 | 异常或次数断言失败 | 默认成功或无条件重试 | 本层保留原异常，不加重试 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位；核心修复由你完成。

## Checkpoint

本单元完成后，应能解释执行依赖、原对象关联、失败反馈与执行异常的区别，以及为何不直接更新累计检查状态。
用户实现与 Review 已通过：新增 27 个用例随全量 256 个测试通过，lint/format 和运行观察通过。
观察时额外断言了原 Action 引用、执行及模型调用次数、反馈传递和状态保留；没有真实文件读取、模型或 GPU 调用。

本单元已提交为 `2048b96 feat: handle tool actions with validated observations`，共 10 个文件；提交后工作区干净。
下一单元见 [步骤记录契约](step-record.md)，由用户实现；有限循环、工具注册、真实执行器和恢复策略保持后续任务。
