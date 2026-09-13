# RUN-003D：审核交付提议后完成任务

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。请求信息处理已提交为
`8b126e3 feat: pause tasks on request input actions`，进入本单元前工作区干净。
进入本单元前的完整验收为 206 个测试及 lint/format 通过。

已有 RequestInputAction 的等待处理。本轮处理第二种行动 FinishAction：
程序侧审核函数明确接受后，才返回 COMPLETED 快照。
本轮只建立审核接口和状态控制，不提前实现真实报告审核、其他行动或完整循环。
当前进度见 [当前能力与验证范围](status.md)。

## Concept

**模型申请交付，程序判断能否接受。** FinishAction 的结构合法，
只能证明字段满足协议，不能证明目标已达成或陈述有充分证据。

因此引入一个由应用程序装配的审核函数 reviewer，它接收 TaskState 和 FinishAction，
返回明确的 True 或 False。模型输出中没有 reviewer 或 accepted 字段，
不能把模型自己写的“审核通过”当成程序的审核结果。
当前测试使用固定返回值的替身；真实审核规则将在报告与证据能力阶段实现。

**为什么现在只返回 bool？** 当前控制流只需要区分接受和拒绝。
遇到需要把拒绝原因交回模型进行修改时，再扩展结构化审核结果；
当前没有拒绝原因列表或自动 Re-planning。
如果直接把 FinishAction 转成 COMPLETED，就没有明确的程序审核位置。
如果把所有业务规则写进 Handler，状态控制与报告检查会混在一起。
一个注入的普通函数足够建立当前边界，不需要新的框架或审核服务。

**拒绝与异常不同。** False 表示审核正常执行但没有接受交付；
审核函数抛错表示审核未正常完成。两者都不应该产生完成状态，
但后续 Runtime 可以分别处理，不能吞掉异常后默认同意。

## Design

| 输入／输出 | 契约 | 用途 |
| --- | --- | --- |
| state | TaskState，当前转换规则要求 RUNNING | 本次交付对应的任务快照 |
| action | FinishAction | 待审核的交付提议 |
| reviewer | 显式提供的 FinishReviewer 可调用对象 | 接收 state/action，返回严格 bool |
| 接受 | 返回 COMPLETED 新快照 | 请求与检查结果保留 |
| 拒绝 | 抛出 FinishRejected | 调用者仍持有原状态 |
| 非法返回／审核异常 | TypeError／原异常向上传播 | 不默认接受，不重试 |

流程图见 [完成审核边界](diagrams/finish-handler.md)，可独立 Markdown 预览。

先用 transition_status 检查能否进入 COMPLETED，再调用 reviewer 一次。
此时只是取得一个合法的目标枚举，没有修改任务。
只有结果严格为 True，才通过 transition_to 构造并返回完成快照。
审核前检查状态，可以防止给等待中或已终止任务重复发起审核。

**任务完成与算子验证独立。** 本轮绝不把 NOT_RUN 自动变成 PASSED。
后续审核器要结合交付范围判断哪些证据必须具备；它不能一概要求所有任务都有性能报告，
也不能接受“未验证但声称已经通过”的交付。
当前返回 True 的测试替身只验证控制流程，不证明这个样例的内容满足真实产品验收标准。

reviewer 是受信任的程序依赖，其签名标注不能自动检查实现是否正确。
当前 Handler 不认证来源、不持久化审核证据、不提供超时或重试，
也不强制阻止调用者绕过它直接使用低层状态 API；后续正式入口必须统一走受控流程。

## Implementation

助手仅准备讲义、图和状态文档。你修改已有核心文件并新增测试。
保留 RUN-003C 的 apply_request_input，不改变它的逻辑。

### 1. 扩展 handlers.py

在 `src/kernellens/runtime/handlers.py` 做三处修改：

1. 增加 Callable、FinishAction 和 transition_status 导入。
2. 在模块顶层添加 FinishReviewer 别名与 FinishRejected 异常类。
3. 在已有处理函数之后添加 apply_finish。

以下是本单元完成后该文件的对照版本。新增核心是审核接口与 apply_finish；
原有请求信息处理保持原样，由你手动完成修改。

```python
from collections.abc import Callable

from kernellens.domain.action import FinishAction, RequestInputAction
from kernellens.domain.state import TaskState, TaskStatus, transition_status

type FinishReviewer = Callable[[TaskState, FinishAction], bool]


class FinishRejected(RuntimeError):
    """Raised when a finish proposal is not accepted."""


def apply_request_input(
    state: TaskState,
    action: RequestInputAction,
) -> TaskState:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(action, RequestInputAction):
        raise TypeError("action must be a RequestInputAction")
    return state.transition_to(TaskStatus.WAITING_INPUT)


def apply_finish(
    state: TaskState,
    action: FinishAction,
    *,
    reviewer: FinishReviewer,
) -> TaskState:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(action, FinishAction):
        raise TypeError("action must be a FinishAction")
    if not callable(reviewer):
        raise TypeError("reviewer must be callable")

    next_status = transition_status(state.status, TaskStatus.COMPLETED)
    accepted = reviewer(state, action)
    if not isinstance(accepted, bool):
        raise TypeError("reviewer must return a bool")
    if not accepted:
        raise FinishRejected("finish action was rejected")
    return state.transition_to(next_status)
```

按逻辑块理解：

- FinishReviewer 延续上一阶段的函数依赖注入，输入两项，输出 bool。
- 参数列表里的单独 `*` 表示 reviewer 必须按名字传入，例如 `reviewer=accept`。
  它没有默认值，调用者必须明确提供审核函数。
- 前置检查确认类型和可调用性；callable 不检查参数签名，错误签名仍会在调用时抛错。
- transition_status 只校验并返回目标枚举；最后的 transition_to 才返回更新后的 TaskState。
  两者都复用同一转换规则，提前检查也不会提前把任务标记完成。
- 审核返回值必须真的是 bool。`"false"` 是非空字符串，直接写 if 会把它当真；
  0 和 1 也不是当前接口接受的审核结论。
- False 对应 FinishRejected；其他审核异常不在这里捕获，不会被伪装为成功。

### 2. 完成审核测试

创建 `tests/test_finish_handler.py`，输入以下测试。
共 8 个测试函数，参数化后 23 个用例。

```python
import pytest

from kernellens.domain.action import (
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.handlers import FinishRejected, apply_finish
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING, task_type=TaskType.DIAGNOSE):
    return TaskState(
        request=TaskRequest(task_type, "交付当前 GEMM 开发结果"),
        status=status,
        verification=VerificationState(syntax=VerificationStatus.PASSED),
    )


def make_action():
    return FinishAction(
        answer="提交当前分析与建议，尚未执行服务器编译验证。",
        reason="申请交付本轮结果。",
    )


def must_not_run(state, value):
    pytest.fail("dependency must not be called for invalid or stopped tasks")


@pytest.mark.parametrize(
    "task_type", [TaskType.GENERATE, TaskType.OPTIMIZE, TaskType.DIAGNOSE]
)
def test_acceptance_completes_task_without_changing_verification(task_type):
    state = make_state(task_type=task_type)
    action = make_action()
    calls = []

    def accept(received_state, received_action):
        calls.append((received_state, received_action))
        return True

    completed = apply_finish(state, action, reviewer=accept)

    assert completed.status is TaskStatus.COMPLETED
    assert state.status is TaskStatus.RUNNING
    assert completed.request is state.request
    assert completed.verification is state.verification
    assert completed.verification.syntax is VerificationStatus.PASSED
    assert completed.verification.compilation is VerificationStatus.NOT_RUN
    assert len(calls) == 1
    assert calls[0][0] is state
    assert calls[0][1] is action
    with pytest.raises(ValueError, match="running"):
        decide_once(completed, must_not_run)


def test_rejection_preserves_running_state():
    state = make_state()
    action = make_action()
    calls = []

    def reject(received_state, received_action):
        calls.append(received_action)
        return False

    with pytest.raises(FinishRejected, match="rejected"):
        apply_finish(state, action, reviewer=reject)
    assert state.status is TaskStatus.RUNNING
    assert calls == [action]


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_invalid_source_state_does_not_call_reviewer(status):
    with pytest.raises(ValueError, match="invalid status transition"):
        apply_finish(make_state(status=status), make_action(), reviewer=must_not_run)


@pytest.mark.parametrize("state", [None, {}])
def test_invalid_state_type_does_not_call_reviewer(state):
    with pytest.raises(TypeError, match="state"):
        apply_finish(state, make_action(), reviewer=must_not_run)


@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        RequestInputAction(question="请补全 shape。", reason="信息不足。"),
        CallToolAction(
            tool_name="read_report",
            arguments={"path": "report.json"},
            reason="读取报告。",
        ),
    ],
)
def test_other_actions_do_not_call_reviewer(action):
    with pytest.raises(TypeError, match="action"):
        apply_finish(make_state(), action, reviewer=must_not_run)


@pytest.mark.parametrize("reviewer", [None, True])
def test_rejects_non_callable_reviewer(reviewer):
    with pytest.raises(TypeError, match="reviewer"):
        apply_finish(make_state(), make_action(), reviewer=reviewer)


@pytest.mark.parametrize("verdict", [None, "false", 0, 1])
def test_non_boolean_verdict_does_not_complete_task(verdict):
    state = make_state()
    calls = []

    def invalid_reviewer(received_state, action):
        calls.append(action)
        return verdict

    with pytest.raises(TypeError, match="bool"):
        apply_finish(state, make_action(), reviewer=invalid_reviewer)
    assert state.status is TaskStatus.RUNNING
    assert len(calls) == 1


def test_reviewer_exception_propagates_without_retry():
    state = make_state()
    calls = []

    def failing_reviewer(received_state, action):
        calls.append(action)
        raise RuntimeError("reviewer unavailable")

    with pytest.raises(RuntimeError, match="reviewer unavailable"):
        apply_finish(state, make_action(), reviewer=failing_reviewer)
    assert state.status is TaskStatus.RUNNING
    assert len(calls) == 1
```

重点检查：

- 接受后才能完成，并保留已有检查结论；完成态不能再调用模型。
- 非法输入和来源状态在审核之前拒绝，must_not_run 防止遗漏这个调用边界。
- False、错误返回类型和审核异常都不产生完成状态；每次有效审核最多调用注入函数一次。
- 测试中的检查状态与审核结果均为手写数据，没有执行真实报告检查。
  三种任务用相同 True 替身，只证明控制接口通用，不证明它们有相同的业务验收条件。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_finish_handler.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

2026-09-09 已对用户实现运行完整回归：**229 passed in 0.13s**，包含本文件的 **23 个新增用例**。
实际命令为 `uv run --locked --offline --no-cache --no-python-downloads pytest -q`；
Ruff lint 与 format 检查通过，共 26 个 Python 文件。
助手仅整理 handlers.py 的函数／类间空行和末尾换行，语法树及去除空白后的文本不变；未修改核心逻辑或测试。

## Observe

实现后，在项目根目录运行整段命令：

```bash
uv run --locked python - <<'PY'
from kernellens.domain.action import FinishAction
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.handlers import FinishRejected, apply_finish


def reject(state, action):
    return False


def accept(state, action):
    return True


state = TaskState(TaskRequest(TaskType.DIAGNOSE, "交付当前诊断结果"))
state = state.transition_to(TaskStatus.RUNNING)
action = FinishAction(answer="提交诊断建议，尚未编译验证。", reason="申请交付。")

try:
    state = apply_finish(state, action, reviewer=reject)
except FinishRejected as error:
    print(error)
print(state.status.value)

state = apply_finish(state, action, reviewer=accept)
print(state.status.value)
print(state.verification.compilation.value)
PY
```

实际本地替身观察输出（2026-09-09）：

```text
finish action was rejected
running
completed
not_run
```

第一次被拒绝，赋值没有发生，原状态仍为 running。
第二次用接受替身演示另一条路径：状态变为 completed，但 compilation 仍是 not_run。
这是手工选择两个测试替身观察分支，不是遇到真实审核拒绝后切换成无条件同意的处理策略。
生产流程应补齐交付材料，再由同一个有效审核策略判断。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入 apply_finish 或 FinishRejected | ImportError | 名称或作用域有误 | 核对两者均在 handlers.py 模块顶层 |
| reviewer 参数调用报错 | 提示缺少 keyword-only 参数 | 没按名字传递 | 使用 reviewer=审核函数，不提前调用它 |
| must_not_run 被触发 | 非运行态仍调用审核 | 审核放在状态检查之前 | 将纯转换检查放在 reviewer 调用之前 |
| False 仍使任务完成 | 拒绝测试未抛异常 | 忽略了审核返回值 | 显式处理拒绝，再返回完成快照 |
| 字符串 false 被当作同意 | 非 bool 返回用例失败 | 使用了真假值转换 | 先严格检查 bool 类型，不用 bool(...) 归一化 |
| 审核异常变成完成状态 | 异常传播测试失败 | 捕获异常后默认接受 | 保留原异常，不在 except/finally 中完成任务 |
| 任务完成后编译变成通过 | NOT_RUN 断言失败 | 把完成与验证混在一起 | 只改变 status，保留 verification 快照 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。

## Checkpoint

本单元应理解：结构校验、交付审核、状态转换和算子验证之间的职责；
学会把可预期拒绝与执行异常分开，并测试失败时不会误报完成。

用户实现与 Review 已通过：新增 23 个用例随全量 229 个测试通过，lint/format 和运行观察通过。
观察时额外核对了原状态引用、请求／检查快照保留及审核调用次数；没有真实模型、工具或服务器调用。

本单元已提交为 `4b8cdff feat: gate task completion on finish review`，共 10 个文件；提交后工作区干净。
下一单元见 [工具行动执行与反馈](tool-call-handler.md)，由用户实现；完整循环和真实报告审核保持后续任务。
