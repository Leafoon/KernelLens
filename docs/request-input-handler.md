# RUN-003C：处理请求信息行动，让任务进入等待态

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。预算模块已提交为
`76dd78d feat: add decision attempt budget`，进入本单元前工作区干净。
最近一次完整验收为 190 个测试及 lint/format 通过。

decide_once 已能返回三种行动提议，DecisionBudget 已能单独限制额度。
现在处理第一个行动：当调用者接受 RequestInputAction 时，把任务转为 WAITING_INPUT。
本单元只实现这一种行动处理；不提前整合预算、工具执行或完整循环。
当前进度见 [当前能力与验证范围](status.md)。

## Concept

**行动提议与行动处理**是两层责任：RequestInputAction 保存问题及理由；
apply_request_input 根据程序规则产生新的等待态快照。

例如，生成 GEMM 时缺少 shape 和 dtype，模型提出请求信息。
运行层应把任务标记为等待，将问题交还应用层，结束当前自动推进。
这里 WAITING_INPUT 是业务状态，不是调用 input() 阻塞 Python 进程，也不是循环轮询用户。

**为什么复用状态转换？** 我们已经在 domain/state.py 定义哪些转换合法。
处理函数只指定目标 WAITING_INPUT，合法性由 transition_to 检查。
当前转换表中只有 RUNNING 可以进入 WAITING_INPUT，因此不用在这里复制一份状态表。
这个边界需要组合测试：未来状态规则改变时，测试会提示行动处理行为是否也发生变化。

一个普通函数足够表达当前规则。以后按实际行动增加处理逻辑；不需要引入事件总线或工作流框架。

## Design

| 输入／输出 | 契约 | 用途 |
| --- | --- | --- |
| state | TaskState，当前转换规则要求 RUNNING | 待处理任务的最新快照 |
| action | RequestInputAction | 调用者选择应用的请求信息提议 |
| 返回值 | 新 TaskState，status 为 WAITING_INPUT | 交给调用者保存 |
| 保留内容 | 原 request 与 verification | 暂停不会清空目标或改写检查结论 |

专项图见 [请求信息行动处理](diagrams/request-input-handler.md)，可独立 Markdown 预览。

控制流：检查输入类型 → 调用已有 transition_to → 返回新快照。
非法类型抛 TypeError，非法状态转换复用已有 ValueError；失败时不产生新状态。

函数只处理任务状态，action 中的问题与理由仍留在原行动对象。
调用者需要同时保留 action 和返回的新状态，供后续应用层展示与运行记录使用；
TaskState 目前没有保存“待回答的问题”。跨进程存储与输入恢复在后续设计。
本轮也不判断问题是否确有必要或已经问过：那需要实际任务上下文。

后续模型调用必须使用最新状态。旧快照仍为 RUNNING，不能拿它继续推进；
运行层必须保存新快照并停止本轮自动执行。状态对象本身不是防绕过或并发控制机制。
当前预算对象不会被消耗、重建或清零；本函数不持有它，也尚未完成预算集成。

## Implementation

助手仅准备本文、专项图及相关状态文档，现有核心文件保持不变。
两个新核心文件由用户创建。

### 1. 第一个行动处理函数

创建 `src/kernellens/runtime/handlers.py` 并输入：

```python
from kernellens.domain.action import RequestInputAction
from kernellens.domain.state import TaskState, TaskStatus


def apply_request_input(
    state: TaskState,
    action: RequestInputAction,
) -> TaskState:
    if not isinstance(state, TaskState):
        raise TypeError("state must be a TaskState")
    if not isinstance(action, RequestInputAction):
        raise TypeError("action must be a RequestInputAction")
    return state.transition_to(TaskStatus.WAITING_INPUT)
```

按逻辑块理解：

1. 接收的是经过构造或 Parser 校验的 RequestInputAction 对象，不是原始模型字典。
2. 两个 isinstance 检查保护直接调用入口；FinishAction 和 CallToolAction 不能被误当作请求信息处理。
3. 最后一行复用 TaskState.transition_to。它检查转换规则，并通过 replace 返回新对象。
   处理函数不复制状态机、不调用模型，也不修改传入对象。
4. action.question 没有被读取，是因为这层只处理生命周期；展示问题由后续应用层负责。
   原行动对象仍保留完整文本，测试会检查它没有被改写。

### 2. 行动与状态的组合测试

创建 `tests/test_request_input_handler.py`，输入以下代码。
共 5 个测试函数，参数化后 16 个用例。

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
from kernellens.runtime.handlers import apply_request_input
from kernellens.runtime.step import decide_once


def make_state(status=TaskStatus.RUNNING, task_type=TaskType.DIAGNOSE):
    return TaskState(
        request=TaskRequest(task_type, "完善 GEMM 开发需求"),
        status=status,
        verification=VerificationState(syntax=VerificationStatus.PASSED),
    )


def make_action():
    return RequestInputAction(
        question="请提供 GEMM 的 shape 和 dtype。",
        reason="当前计算契约不完整。",
    )


@pytest.mark.parametrize(
    "task_type", [TaskType.GENERATE, TaskType.OPTIMIZE, TaskType.DIAGNOSE]
)
def test_pauses_task_and_preserves_existing_information(task_type):
    original = make_state(task_type=task_type)
    action = make_action()

    paused = apply_request_input(original, action)

    assert paused.status is TaskStatus.WAITING_INPUT
    assert original.status is TaskStatus.RUNNING
    assert paused is not original
    assert paused.request is original.request
    assert paused.verification is original.verification
    assert paused.verification.syntax is VerificationStatus.PASSED
    assert paused.verification.compilation is VerificationStatus.NOT_RUN
    assert action.question == "请提供 GEMM 的 shape 和 dtype。"


@pytest.mark.parametrize(
    "status", [status for status in TaskStatus if status is not TaskStatus.RUNNING]
)
def test_rejects_invalid_source_states(status):
    with pytest.raises(ValueError, match="invalid status transition"):
        apply_request_input(make_state(status=status), make_action())


@pytest.mark.parametrize("state", [None, {}])
def test_rejects_non_task_state(state):
    with pytest.raises(TypeError, match="state"):
        apply_request_input(state, make_action())


@pytest.mark.parametrize(
    "action",
    [
        None,
        {},
        FinishAction(answer="提交当前分析。", reason="本轮分析结束。"),
        CallToolAction(
            tool_name="read_report",
            arguments={"path": "report.json"},
            reason="读取报告。",
        ),
    ],
)
def test_rejects_other_actions(action):
    with pytest.raises(TypeError, match="action"):
        apply_request_input(make_state(), action)


def test_paused_task_cannot_start_another_decision():
    paused = apply_request_input(make_state(), make_action())

    def must_not_run(state, observations):
        pytest.fail("model must not be called while waiting for input")

    with pytest.raises(ValueError, match="running"):
        decide_once(paused, must_not_run)
    assert paused.status is TaskStatus.WAITING_INPUT
```

测试重点：

- 同一个暂停规则服务于生成、优化和诊断三种任务。
- 状态改变时，原请求与已有检查快照保留；测试里的 PASSED 是手写数据，未执行真实检查。
- 非 RUNNING 的六种状态和其他类型行动都被拒绝。
- 最后一个测试把处理函数与已有 decide_once 串联；如果等待态仍调用模型，must_not_run 会使测试失败。

这证明“处理后的状态进入现有决策入口会被拒绝”，不代表已存在自动停止的完整循环。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_request_input_handler.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

新测试预期 **16 passed**；全量回归 `uv run --locked pytest -q` 预期 **206 passed**。
用户实现已验收：全量实测 206 passed，包含本单元的 16 个用例；lint/format 通过。

## Observe

实现后，在项目根目录运行整段命令：

```bash
uv run --locked python - <<'PY'
from kernellens.domain.action import RequestInputAction
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.handlers import apply_request_input
from kernellens.runtime.step import decide_once

calls = []


def fake_model(state, observations):
    calls.append(state)
    return {
        "kind": "request_input",
        "question": "请提供 GEMM 的 shape 和 dtype。",
        "reason": "当前计算契约不完整。",
    }


state = TaskState(TaskRequest(TaskType.GENERATE, "生成一个 GEMM 算子"))
state = state.transition_to(TaskStatus.RUNNING)
action = decide_once(state, fake_model)
assert isinstance(action, RequestInputAction)
print(state.status.value)

state = apply_request_input(state, action)
print(state.status.value)
print(action.question)

try:
    decide_once(state, fake_model)
except ValueError as error:
    print(error)
print(len(calls))
PY
```

预期：

```text
running
waiting_input
请提供 GEMM 的 shape 和 dtype。
state must be running before a decision
1
```

模型提出请求后，状态先保持 running；应用该行动后，才变为 waiting_input。
下一次决策被拒绝，因此替身只调用一次。这是显式调用的本地演示；
没有发送用户消息、使用真实模型或执行算子，也没有开始循环。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入 apply_request_input | ModuleNotFoundError / ImportError | 路径、函数名或作用域有误 | 核对 runtime/handlers.py，函数必须顶格 |
| action 字典被拒绝 | TypeError 提示 RequestInputAction | 绕过了已有解析入口 | 传入 decide_once 的结果或显式构造行动对象 |
| PENDING 直接进入等待失败 | invalid status transition | 任务尚未开始运行 | 先核对调用流程；保持已确定的状态转换规则 |
| 处理后状态仍为 running | 使用了旧 state | 没有接收返回值 | 使用 state = apply_request_input(state, action) |
| 问题字段读取失败 | TaskState 没有 question 属性 | 把行动文本与任务状态混为一层 | 从保留的 action.question 读取，不往 State 临时塞属性 |
| must_not_run 被调用 | 暂停后仍触发模型 | 传入了旧快照或绕开入口检查 | 追踪返回值的保存与下一次 decide_once 使用的对象 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。

## Checkpoint

本单元应掌握：行动处理如何连接模型提议和程序状态，如何复用状态机，
以及为什么必须把最新状态传给后续步骤。

用户实现已通过 Review：206 个测试（含本单元 16 个用例）、lint/format 与运行观察通过。
助手只补齐 handlers.py 的末尾换行，前后 AST 一致；核心逻辑与测试由用户完成。
实际观察：模型提议后仍为 running，应用行动后为 waiting_input，问题文本保留；再次决策拒绝，替身调用次数保持 1。

已由用户提交为 `8b126e3 feat: pause tasks on request input actions`，
包含当前处理函数、组合测试与配套文档；实际提交及干净工作区已核对。
本单元未接入完整循环。当前进度见 [当前能力与验证范围](status.md)。
