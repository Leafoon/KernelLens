# RUN-001D：组合任务状态快照

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。RUN-001C 已提交为 `ae8d080 feat: add per-check verification state`，开始本单元前工作区干净。此前真实应用验收为 62 个测试通过。
TaskRequest、TaskStatus 和 VerificationState 已分别实现。本轮将它们组合为最小 TaskState，提供受转换规则约束的生命周期更新接口。
本文是参考练习，实际实现与验收以 [当前能力与验证范围](status.md) 为准。

## Concept

TaskState 是“某个任务在某一时刻的状态快照”。它同时回答三件事：用户要做什么、任务进行到哪里、各项检查有什么结论。

使用组合：TaskState 保存已有对象，不再复制 goal 和五个检查字段。这样已有的输入校验和验证语义能继续使用，也避免两处保存目标后出现不一致。

使用不可变快照：转换成功时返回新对象，旧对象保持原样；失败时抛异常，不返回新状态。后续 Runtime 可以显式接收返回值，再记录发生了什么变化。
这为观察和测试提供基础，但不会自动保存历史、提供数据库事务或解决并发更新。

## Design

| 成员 | 输入与默认值 | 职责 |
| --- | --- | --- |
| request | 必须传入 TaskRequest | 保留用户的原始任务请求 |
| status | TaskStatus，默认 PENDING | 当前生命周期位置 |
| verification | VerificationState，默认新建全 NOT_RUN 快照 | 保存独立检查结论 |
| transition_to(target) | target 必须是 TaskStatus | 复用 transition_status，返回只改变 status 的新 TaskState |

构造时校验三个字段的类型。生命周期更新不改 request 或 verification。非法边抛 ValueError，错误类型抛 TypeError。
具体更新流程见独立图源 [task-state.md](diagrams/task-state.md)。

本轮只组合三个字段。run ID、步数与预算、候选、证据及持久化将在实际消费者出现时逐项加入。

边界：构造函数允许显式传入某个合法类型的 status，用于表达一个快照；它没有上一时刻的信息，不能验证转换历史。只有 transition_to 执行本轮的转换检查。
例如手动构造 COMPLETED，或直接调用 dataclasses.replace 修改 status，都不能证明任务按规则运行过。后续 Runtime 应通过 transition_to 更新生命周期，不把原始构造或 replace 暴露为模型可调用能力。
本对象是领域契约，不是防止任意 Python 代码绕过规则的安全边界。COMPLETED 的报告验收仍由后续业务模块负责。

继续使用标准库，不引入新依赖。TaskState 放在已有 state.py，因为它直接组合该文件的生命周期规则。
依赖方向为 state → task / verification；task.py 和 verification.py 不反向导入 state.py，避免循环导入。

## Implementation

核心实现与测试由用户亲手输入。助手只保存本讲义、专项图和状态文档。

### 文件一：修改 src/kernellens/domain/state.py

将文件顶部的导入整理成下面这样，保留原有 TaskStatus、_ALLOWED_TRANSITIONS 和 transition_status：

```python
from dataclasses import dataclass, field, replace
from enum import StrEnum

from kernellens.domain.task import TaskRequest
from kernellens.domain.verification import VerificationState
```

然后在 transition_status 函数结束后添加下面的类，注意类位于文件顶层，与函数之间空两行：

```python
@dataclass(frozen=True)
class TaskState:
    request: TaskRequest
    status: TaskStatus = TaskStatus.PENDING
    verification: VerificationState = field(default_factory=VerificationState)

    def __post_init__(self) -> None:
        if not isinstance(self.request, TaskRequest):
            raise TypeError("request must be a TaskRequest")
        if not isinstance(self.status, TaskStatus):
            raise TypeError("status must be a TaskStatus")
        if not isinstance(self.verification, VerificationState):
            raise TypeError("verification must be a VerificationState")

    def transition_to(self, target: TaskStatus) -> "TaskState":
        next_status = transition_status(self.status, target)
        return replace(self, status=next_status)
```

按逻辑块理解：

1. request 保存已有 TaskRequest；读取目标用 state.request.goal。status 和 verification 分别描述不同维度。
2. default_factory 接收可调用对象 VerificationState，不加括号。省略 verification 时，dataclass 会调用它，为这次构造创建默认检查快照。
3. VerificationState 当前是 frozen 的，直接使用一个不可变默认对象未必会产生共享修改问题；这里选择工厂是为了明确每个任务分别初始化检查状态。不要把它误解成现有验证对象可变。
4. __post_init__ 在构造时检查真实类型。类型标注本身不执行校验；被组合对象已负责自己的内部字段约束。
5. transition_to 先调用已有纯函数，避免复制转换表；失败会直接抛出异常，下一行不会执行。
6. replace 创建同类型的新 dataclass，只替换 status，其他字段沿用原对象的值，并重新执行构造校验。这是浅层替换，不是递归深拷贝；本轮被共享的 TaskRequest 和 VerificationState 都禁止常规字段重新赋值。
7. 返回类型写成字符串 "TaskState"，因为定义方法时类名还没有完成绑定。

调用时区分 `next_state = state.transition_to(...)` 和 `state = state.transition_to(...)`：前者保留两个快照引用，后者让变量指向新快照。只调用方法而不接收返回值，不会改变原对象。

### 文件二：新建 tests/test_task_state.py

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus


def test_new_task_starts_pending_with_unrun_checks():
    request = TaskRequest(TaskType.GENERATE, "生成基础 GEMM")
    state = TaskState(request=request)

    assert state.request is request
    assert state.status is TaskStatus.PENDING
    assert state.verification == VerificationState()


def test_transition_preserves_request_and_verification():
    request = TaskRequest(TaskType.DIAGNOSE, "  分析服务器编译失败  ")
    checks = VerificationState(compilation=VerificationStatus.FAILED)
    before = TaskState(request=request, verification=checks)

    after = before.transition_to(TaskStatus.RUNNING)

    assert after is not before
    assert before.status is TaskStatus.PENDING
    assert after.status is TaskStatus.RUNNING
    assert after.request is request
    assert after.verification is checks


def test_completion_does_not_mark_checks_as_passed():
    state = TaskState(TaskRequest(TaskType.GENERATE, "交付 GEMM 候选和运行说明"))
    running = state.transition_to(TaskStatus.RUNNING)

    completed = running.transition_to(TaskStatus.COMPLETED)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.verification is running.verification
    assert completed.verification == VerificationState()


def test_illegal_transition_preserves_current_snapshot():
    state = TaskState(TaskRequest(TaskType.OPTIMIZE, "提出 GEMM 优化候选"))

    with pytest.raises(ValueError, match="pending -> completed"):
        state = state.transition_to(TaskStatus.COMPLETED)

    assert state.status is TaskStatus.PENDING


@pytest.mark.parametrize("target", ["running", VerificationStatus.FAILED])
def test_transition_rejects_wrong_target_type(target):
    state = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))

    with pytest.raises(TypeError, match="TaskStatus"):
        state.transition_to(target)

    assert state.status is TaskStatus.PENDING


@pytest.mark.parametrize(
    "field_name, value",
    [("request", None), ("status", "pending"), ("verification", None)],
)
def test_snapshot_rejects_wrong_field_type(field_name, value):
    arguments = {"request": TaskRequest(TaskType.GENERATE, "生成基础 GEMM")}
    arguments[field_name] = value

    with pytest.raises(TypeError, match=field_name):
        TaskState(**arguments)


def test_lifecycle_cannot_be_reassigned_directly():
    state = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))

    with pytest.raises(FrozenInstanceError):
        state.status = TaskStatus.COMPLETED
```

七个测试函数展开为 10 个用例；重点检查组合行为，不重新复制已有的生命周期转换矩阵。
`is` 检查是否仍是同一个请求／检查对象，`== VerificationState()` 比较五项结果是否仍等于默认 NOT_RUN。
字段类型测试的 `**arguments` 把字典展开为关键字参数，例如 `{"request": request}` 相当于 `request=request`。
测试中的检查失败是手动构造的状态，完成也只是合法生命周期边；它们不代表已执行真实编译或通过业务验收。

## Run

在项目根保存文件后执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

按参考实现预期 72 passed：已有 62 个，本轮新增 10 个。这是验收目标，实际结果以 docs/status.md 为准。
若只有格式问题，运行 `uv run --locked ruff format src tests`，再查看变化并复查。

## Observe

运行 `uv run --locked python`，逐行输入：

```python
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
pending = TaskState(TaskRequest(TaskType.GENERATE, "生成基础 GEMM"))
running = pending.transition_to(TaskStatus.RUNNING)
completed = running.transition_to(TaskStatus.COMPLETED)
print(pending.status.value, running.status.value, completed.status.value)
print(completed.request is pending.request)
print(completed.verification is pending.verification)
print(completed.verification.compilation.value)
print(pending.status.value)
pending = pending.transition_to(TaskStatus.COMPLETED)
print(pending.status.value)
```

前五次打印依次为：

```text
pending running completed
True
True
not_run
pending
```

倒数第二行应抛 `ValueError: invalid status transition: pending -> completed`。在交互解释器中，异常后仍可输入最后一行，应打印 pending：右侧失败，左侧赋值没有发生。
使用 exit() 退出。这一观察也说明：完成快照和旧快照共享同一个未运行检查对象，生命周期没有替它编造验证结论。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| FrozenInstanceError 出现在合法转换中 | 堆栈指向 self.status = ... | 直接修改了快照 | 查看赋值行，改成校验后 replace 并返回 |
| 调用成功但原变量仍为 pending | 方法没有异常，变量值未变 | 没有接收返回值 | 给返回值一个变量名，再观察两个对象 |
| 更新后检查结果丢失 | after.verification is checks 失败 | 重建 TaskState 时漏传已有检查 | 检查是否使用 replace 保留其他字段 |
| pending 可以直接 completed | 非法边测试 DID NOT RAISE | 跳过 transition_status | 确认先校验再创建新对象，不改断言 |
| 默认创建时提示对象不可调用 | 堆栈指向默认工厂 | 写成 default_factory=VerificationState() | 工厂应接收类本身，去掉括号 |
| 无法导入 TaskState | ImportError | 类未保存或放错缩进位置 | 检查 state.py 中 TaskState 位于文件顶层 |

先保留失败输出，按 Problem → Evidence → Hypothesis → Verification → Fix 定位，再由用户修改核心逻辑。

## Checkpoint

本单元目标：理解对象组合、默认工厂、不可变快照、显式状态更新及其与历史保存的区别；验证生命周期变化保留原请求和检查结果。
输入代码并运行、观察后，回复“已完成”或“帮我检查”，助手读取实际文件再 Review。通过检查前不提交功能完成记录。
验收后建议 `feat: compose immutable task state`，包含 state.py、组合测试、讲义、专项图和相关文档。这是一个可独立验证的状态功能，适合作为 Git Checkpoint。
本轮停在 TaskState，不提前实现 Runtime、Action、预算或持久化。
