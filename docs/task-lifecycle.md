# RUN-001B：任务生命周期与状态转换

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。RUN-001A 已由用户提交为 `c5a5e9c feat: add task request contract`；配置与任务请求的最近验收为 12 个测试通过。
本单元只定义 TaskStatus 和转换规则。用户亲手输入状态逻辑及测试；本页参考代码不表示应用已实现，实际记录见 [当前能力与验证范围](status.md)。

## Concept

TaskRequest 保存用户想完成什么；生命周期描述任务现在进行到哪里。
只记录一句“正在处理”无法可靠判断任务是否已开始、是否在等待输入、能否继续执行。
有限状态机由有限的状态和允许的转换组成，将这些规则变成可以检查的代码。

例如生成 GEMM 的任务可能经历：待启动 → 运行 → 发现 shape 缺失 → 等待输入 → 收到补充 → 继续运行 → 完成交付。
waiting_input 是暂停状态，仍有后续动作；completed、failed、cancelled、budget_exhausted 是终态，本次任务不再继续。
这里的等待与继续只定义规则，不实现 API、持久化恢复、计时器或模型调用。

## Design

图源独立保存为 [task-lifecycle.md](diagrams/task-lifecycle.md)，可在 VS Code Markdown 预览。

| 当前状态 | 含义 | 允许的下一状态 |
| --- | --- | --- |
| pending | 请求已接受，等待启动 | running、cancelled |
| running | 正在处理任务 | waiting_input、completed、failed、cancelled、budget_exhausted |
| waiting_input | 等待用户补充信息 | running、failed、cancelled |
| completed | 满足当前任务的交付要求 | 无 |
| failed | 任务因无法恢复的错误终止 | 无 |
| cancelled | 任务被取消 | 无 |
| budget_exhausted | 任务耗尽执行预算 | 无 |

本版规则的理由：

- 执行前初始化检查计入 running，因此 pending 不直接完成或失败；开始前可以取消。
- 等待期间可以因等待请求失效等无法恢复的错误而失败，也可以取消；补充输入后需先回到 running，再判断能否完成。
- 本版执行预算在 running 时检查。将来若引入包含等待时间的总截止时间，再依据需求调整转换规则。
- 同状态转换也拒绝：步骤中仍在运行时无需触发生命周期转换。重规划可发生在 running 内部。
- 终态没有出边，不能把已完成或已失败的任务直接改回 running。重新尝试应显式创建新运行；V1 的 interrupted 与恢复语义另行设计。

函数接口：`transition_status(current: TaskStatus, target: TaskStatus) -> TaskStatus`。
输入是当前状态与拟切换的状态；合法时返回 target，类型不符时抛 TypeError，边不允许时抛 ValueError 并报告起点和终点。
这是纯函数：只计算结果，不修改传入对象、不保存状态、不执行外部操作。
调用者以后通过 `status = transition_status(status, target)` 接受新状态；函数抛错时赋值不会发生。

生命周期合法只是必要条件。running → completed 的边本身不证明交付合格，更不证明算子已验证。后续 Runtime 必须在验收条件满足后使用这条边。
本单元不创建完整 TaskState；它会在后续将请求、状态和运行信息组合起来。

继续用现有 Python 标准库。转换表集中表达当前规则，避免调用者各写一套 if/else；尚不需要状态机框架或 Workflow 服务。

## Implementation

本轮无需新增工程依赖或包目录。下面两个文件都由用户创建。

### 文件一：src/kernellens/domain/state.py

```python
from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


_ALLOWED_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_INPUT,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BUDGET_EXHAUSTED,
    },
    TaskStatus.WAITING_INPUT: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.BUDGET_EXHAUSTED: set(),
}


def transition_status(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if not isinstance(current, TaskStatus) or not isinstance(target, TaskStatus):
        raise TypeError("current and target must be TaskStatus values")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"invalid status transition: {current.value} -> {target.value}"
        )
    return target
```

逻辑块说明：

1. TaskStatus 定义词汇；它与 TaskType 不同，前者是进展，后者是业务目标。
2. `_ALLOWED_TRANSITIONS` 是模块内部使用的规则表。键是起点，集合是允许的终点；`set()` 是空集合，表示没有任何出口。表不由调用者修改。
3. 先检查枚举类型，避免普通字符串混入。随后只做集合成员判断，将规则和执行校验分开。
4. 非法转换包含起点和终点，方便之后从错误或 trace 定位。合法时返回新状态，调用者决定何时保存。
5. 新增状态时需要同时更新规则表和测试；本单元表覆盖全部七个状态。

### 文件二：tests/test_state.py

```python
import pytest

from kernellens.domain.state import TaskStatus, transition_status


def test_task_can_wait_resume_and_complete():
    status = TaskStatus.PENDING
    for target in (
        TaskStatus.RUNNING,
        TaskStatus.WAITING_INPUT,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
    ):
        status = transition_status(status, target)
        assert status is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.PENDING),
        (TaskStatus.WAITING_INPUT, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.RUNNING),
    ],
)
def test_invalid_transition_preserves_current_status(current, target):
    status = current
    with pytest.raises(ValueError, match=f"{current.value} -> {target.value}"):
        status = transition_status(status, target)
    assert status is current


@pytest.mark.parametrize(
    "terminal",
    [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BUDGET_EXHAUSTED,
    ],
)
@pytest.mark.parametrize("target", list(TaskStatus))
def test_terminal_states_have_no_exit(terminal, target):
    with pytest.raises(ValueError):
        transition_status(terminal, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("running", TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, "completed"),
    ],
)
def test_rejects_raw_status_strings(current, target):
    with pytest.raises(TypeError, match="TaskStatus"):
        transition_status(current, target)


def test_task_can_be_cancelled_before_starting():
    assert (
        transition_status(TaskStatus.PENDING, TaskStatus.CANCELLED)
        is TaskStatus.CANCELLED
    )


@pytest.mark.parametrize(
    "target",
    [TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BUDGET_EXHAUSTED],
)
def test_running_task_can_stop_without_completion(target):
    assert transition_status(TaskStatus.RUNNING, target) is target
```

测试从业务路径与不变量出发，不从实现中的转换表生成预期结果：

- 一条真实的等待、继续、交付路径。
- 四种非法转换，失败后当前状态不变。
- 四种终态乘以七种目标，共 28 个组合，验证终态没有出口；两层 parametrize 会展开所有组合。
- 两个错误类型输入、开始前取消，以及运行中三种非完成终止。

共 39 个新用例；与已有 12 个合计，验收目标是 51 passed。测试数主要来自组合展开。
保持 tests 平铺；尚不创建 tests/unit 等新的分层目录。

## Run

保存两个文件后，在项目根执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期 `51 passed`，两项 Ruff 检查通过。这是用户完成实现后的目标，当前实际测试状态见 docs/status.md。
如仅存在排版问题，运行 `uv run --locked ruff format src tests` 后阅读结果并复查。

## Observe

运行 `uv run --locked python`，逐行输入：

```python
from kernellens.domain.state import TaskStatus, transition_status
status = TaskStatus.PENDING
status = transition_status(status, TaskStatus.RUNNING)
print(status.value)
status = transition_status(status, TaskStatus.COMPLETED)
print(status.value)
status = transition_status(status, TaskStatus.RUNNING)
print(status.value)
```

前两次打印应为 running、completed。倒数第二行应抛出 ValueError，消息包含 completed -> running。
在交互式 Python 中继续输入最后一行，仍应打印 completed：右侧函数抛错，左侧赋值没有发生。观察后用 exit() 退出。
这证明当前函数拒绝了非法转换；尚未证明未来 Runtime 会始终调用它或满足交付条件。

## Debug

| Problem | Evidence | Hypothesis | Verification / Fix |
| --- | --- | --- | --- |
| 找不到 state 模块 | ModuleNotFoundError | 文件位置或保存不正确 | 核对 src/kernellens/domain/state.py，通过 uv run 导入 |
| 状态意外变成 None | assert 的实际值为 None | 合法分支缺少 return target | 检查函数返回路径 |
| 非法转换没有报错 | DID NOT RAISE | 成员判断反向或规则表多写了边 | 对照图与具体失败的起点、终点 |
| 原始字符串被接受 | 预期 TypeError 的测试失败 | 漏掉类型检查 | StrEnum 可与字符串比较，成员判断不能替代类型检查 |
| 终态能再次运行 | terminal/target 组合失败 | 终态集合不是空集合 | 对照终态不变量；不修改测试来允许重启 |

遵循 Problem → Evidence → Hypothesis → Verification → Fix。出现失败先保留报错，用户修改核心逻辑后再检查。

## Checkpoint

本轮学习有限状态机、转换表、纯函数、终态，以及转换规则与业务验收的区别。
用户完成实现与观察后回复“已完成”或“帮我检查”；助手先 Review 和验收，不提前实现完整 TaskState、验证状态或 Runtime。
通过后建议提交 `feat: add task lifecycle transitions`，包含状态规则、测试、教学文档和生命周期图；提交前审阅暂存范围，实际验收和提交状态见 docs/status.md。
