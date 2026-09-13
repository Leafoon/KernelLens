# RUN-003F：记录一次决策尝试的处理结果

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前处于 Phase 2 — State & Minimal Runtime。RUN-003E 已提交为
`2048b96 feat: handle tool actions with validated observations`，进入本单元前工作区干净。
进入本单元前的完整验收为 256 个测试及 lint/format、运行观察通过。

单次决策、额度和三个行动 Handler 已具备。接下来要把它们放进有限循环，
首先明确每轮结束后留下什么记录，避免只返回最后答案而丢失失败步骤。
这是 Phase 2 原有“状态轨迹”交付的一部分，本步只实现 StepRecord；循环与运行结果汇总后续接入。

## Concept

**当前状态和步骤记录用途不同。** TaskState 表达任务目前的请求、生命周期和验证状态。
StepRecord 保存某次决策尝试处理结束时的材料：行动是什么、工具返回了什么、出现什么错误、当时状态是什么。
后续任务进入新的状态，旧记录仍引用此前的不可变 TaskState 快照。

**失败发生的位置决定哪些字段存在。** 模型调用或解析失败时，还没有合法 Action。
行动已经解析成功但 Handler 抛错时，可以同时保存 Action 和错误。
工具正常返回 FAILED 是一份 Observation，本版不会再把同一次正常返回记成执行异常。

**记录由程序创建。** 记录类负责字段类型和局部关联，不证明这些事情实际发生过。
记录构造成功不等于模型调用、工具执行、审核或算子验证成功。
将来的循环负责在实际尝试后创建记录、使用已消耗的预算序号，并按顺序保存。
本步没有自动编号、预算更新、序列连续性检查、证据认证或落盘。
没有开始新决策的预算耗尽，不应虚构一条新的决策尝试记录。

**为什么现在用冻结 dataclass？** 一份命名明确的快照比散落的局部变量或任意字典更容易检查。
现有 Action、TaskState 和 ToolObservation 都已有契约，可以直接组合；不需要第三方依赖。
冻结字段防止普通赋值覆盖历史，底层字段复用现有不可变对象；这不等于防篡改存储。
正式 Trace 的耗时、Token、成本、调用标识和持久化按真实接入需求扩展。

## Design

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| decision_number | int，正数且不接受 bool | 运行内这次决策尝试的序号，由调用者提供 |
| state_after | TaskState | 本轮处理结束时的状态快照 |
| action | AgentAction 或 None | 已解析的行动；模型或解析出错时可为空 |
| observation | ToolObservation 或 None | 正常返回的工具反馈，包括 FAILED |
| error | 非空 str 或 None | 未正常取得反馈或处理未完成时的错误摘要，保留原文 |

本版允许的结果组合：

| 情况 | action | observation | error |
| --- | --- | --- | --- |
| 模型／解析出错 | None | None | 必须提供 |
| 请求信息或完成处理正常返回 | 对应 Action | None | None |
| 工具调用正常返回 | CallToolAction | 必须关联原 Action | None |
| 行动处理抛错／审核拒绝 | 已有 Action | None | 必须提供 |

至少要有行动或错误。工具行动必须有反馈或错误；Observation 和 error 不能同时存在。
这是一轮 Handler 正常返回或抛错的两条路径，FAILED 反馈仍属于正常返回。
若未来需要表达“部分反馈与异常同时存在”，应按实际场景扩展契约。

示意图见 [步骤记录与历史快照](diagrams/step-record.md)。
state_after 的转换由 Runtime 复用现有状态机完成，记录构造器只检查它是 TaskState，
不另建一套 Action → 状态规则，也不核验转换历史。
例如审核拒绝后如何继续由运行策略决定，本步不会替它选择 FAILED 或 RUNNING。

接口：`StepRecord(...) -> StepRecord`；非法材料抛 TypeError 或 ValueError。
默认值 None 用于表达缺失字段，并不允许创建 action 和 error 都为空的空记录。
当前不调用模型、执行工具或合并 observation.verification。

## Implementation

本单元新增一个核心文件和一个测试文件，均由你输入；已有 Handler 和 State 保持原样。

### 1. 创建记录模型

文件：`src/kernellens/runtime/records.py`。

```python
from dataclasses import dataclass

from kernellens.domain.action import (
    AgentAction,
    CallToolAction,
    FinishAction,
    RequestInputAction,
)
from kernellens.domain.observation import ToolObservation
from kernellens.domain.state import TaskState


@dataclass(frozen=True)
class StepRecord:
    decision_number: int
    state_after: TaskState
    action: AgentAction | None = None
    observation: ToolObservation | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.decision_number, bool) or not isinstance(
            self.decision_number, int
        ):
            raise TypeError("decision_number must be an integer, not bool")
        if self.decision_number < 1:
            raise ValueError("decision_number must be positive")
        if not isinstance(self.state_after, TaskState):
            raise TypeError("state_after must be a TaskState")
        if self.action is not None and not isinstance(
            self.action, (RequestInputAction, CallToolAction, FinishAction)
        ):
            raise TypeError("action must be an AgentAction or None")
        if self.observation is not None and not isinstance(
            self.observation, ToolObservation
        ):
            raise TypeError("observation must be a ToolObservation or None")
        if self.error is not None:
            if not isinstance(self.error, str):
                raise TypeError("error must be a string or None")
            if not self.error.strip():
                raise ValueError("error must not be blank")

        if self.action is None and self.error is None:
            raise ValueError("record must contain an action or error")
        if self.observation is not None:
            if (
                not isinstance(self.action, CallToolAction)
                or self.observation.action is not self.action
            ):
                raise ValueError("observation must reference the recorded tool action")
            if self.error is not None:
                raise ValueError("record cannot contain both observation and error")
        if (
            isinstance(self.action, CallToolAction)
            and self.observation is None
            and self.error is None
        ):
            raise ValueError("tool action record must contain observation or error")
```

按逻辑块理解：

- 五个字段组合本次尝试的材料；state_after 的名字说明它保存的是处理后的快照。
- 前半段检查字段类型：序号拒绝 bool，error 允许 None，但字符串不能只有空白。
- AgentAction 是类型别名；运行时检查具体的三种行动类，不把注解当作自动验证。
- action 和 error 都为空时没有可记录的结果，应拒绝。
- Observation 必须引用当前记录中的原 CallToolAction，不能只比较字段值。
- Observation 与异常摘要互斥；工具行动缺少两者时也不完整。
- 构造器不推导新状态、不执行行动；冻结对象保存的是调用者提供的快照。

### 2. 创建记录测试

文件：`tests/test_step_record.py`。共 10 个测试函数，参数化后 26 个用例。

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction, FinishAction, RequestInputAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.domain.verification import VerificationState, VerificationStatus
from kernellens.runtime.records import StepRecord


def make_state(status=TaskStatus.RUNNING):
    return TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"), status=status)


def make_tool_action():
    return CallToolAction(
        tool_name="read_report",
        arguments={"path": "report.json"},
        reason="读取执行反馈。",
    )


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (
            RequestInputAction(question="请提供报告。", reason="缺少证据。"),
            TaskStatus.WAITING_INPUT,
        ),
        (
            FinishAction(answer="提交诊断建议。", reason="本轮交付已审核。"),
            TaskStatus.COMPLETED,
        ),
    ],
)
def test_records_non_tool_actions(action, status):
    state = make_state(status)
    record = StepRecord(1, state, action)

    assert record.decision_number == 1
    assert record.state_after is state
    assert record.action is action
    assert record.observation is None
    assert record.error is None


@pytest.mark.parametrize(
    "status", [ToolExecutionStatus.SUCCEEDED, ToolExecutionStatus.FAILED]
)
def test_records_tool_feedback_without_merging_checks(status):
    state = make_state()
    action = make_tool_action()
    report = VerificationState(compilation=VerificationStatus.FAILED)
    observation = ToolObservation(action, status, "固定报告反馈。", report)

    record = StepRecord(2, state, action, observation)

    assert record.decision_number == 2
    assert record.state_after is state
    assert record.action is action
    assert record.observation is observation
    assert record.observation.verification is report
    assert record.state_after.verification.compilation is VerificationStatus.NOT_RUN
    assert record.error is None


@pytest.mark.parametrize(
    "action",
    [
        None,
        make_tool_action(),
        FinishAction(answer="提交当前建议。", reason="申请审核。"),
    ],
)
def test_records_errors_before_or_after_action(action):
    state = make_state(TaskStatus.FAILED)
    error = "  dependency unavailable\n"

    record = StepRecord(1, state, action, error=error)

    assert record.state_after is state
    assert record.action is action
    assert record.error == error
    assert record.observation is None


@pytest.mark.parametrize(
    ("number", "expected_error"),
    [
        (True, TypeError),
        (1.5, TypeError),
        ("1", TypeError),
        (None, TypeError),
        (0, ValueError),
        (-1, ValueError),
    ],
)
def test_rejects_invalid_decision_number(number, expected_error):
    with pytest.raises(expected_error, match="decision_number"):
        StepRecord(number, make_state(), error="model unavailable")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_after", None),
        ("action", {}),
        ("observation", {}),
        ("error", 1),
    ],
)
def test_rejects_invalid_field_types(field, value):
    values = {
        "decision_number": 1,
        "state_after": make_state(),
        "error": "model unavailable",
    }
    values[field] = value
    with pytest.raises(TypeError, match=field):
        StepRecord(**values)


@pytest.mark.parametrize("error", ["", "   "])
def test_rejects_blank_error(error):
    with pytest.raises(ValueError, match="blank"):
        StepRecord(1, make_state(), error=error)


@pytest.mark.parametrize("action", [None, make_tool_action()])
def test_rejects_records_without_an_outcome(action):
    with pytest.raises(ValueError, match="record must contain"):
        StepRecord(1, make_state(), action)


@pytest.mark.parametrize(
    "action",
    [
        RequestInputAction(question="请提供报告。", reason="信息不足。"),
        FinishAction(answer="提交当前建议。", reason="申请审核。"),
        make_tool_action(),
    ],
)
def test_rejects_observation_for_a_different_recorded_action(action):
    original_action = make_tool_action()
    assert original_action is not action
    if isinstance(action, CallToolAction):
        assert original_action == action
    observation = ToolObservation(
        original_action, ToolExecutionStatus.SUCCEEDED, "工具反馈。"
    )

    with pytest.raises(ValueError, match="recorded tool action"):
        StepRecord(1, make_state(), action, observation)


def test_rejects_observation_and_error_together():
    action = make_tool_action()
    observation = ToolObservation(action, ToolExecutionStatus.FAILED, "文件不存在。")

    with pytest.raises(ValueError, match="both observation and error"):
        StepRecord(1, make_state(), action, observation, error="executor unavailable")


def test_record_is_frozen():
    record = StepRecord(1, make_state(TaskStatus.FAILED), error="model unavailable")

    with pytest.raises(FrozenInstanceError):
        record.decision_number = 2
```

| 测试组 | 用例数 | 验证目的 |
| --- | ---: | --- |
| 请求信息／完成行动 | 2 | 保留原行动和处理后状态 |
| 成功／失败工具反馈 | 2 | 保留原反馈，不合并累计检查 |
| 无行动／工具行动／完成行动后的错误 | 3 | 错误位置不同，记录材料不同；保留错误原文 |
| 非法序号 | 6 | 区分类型错误、bool 和非正数 |
| 非法字段类型 | 4 | state_after、action、observation、error 的边界 |
| 空错误文本 | 2 | None 与空字符串含义不同 |
| 缺少结果 | 2 | 拒绝空记录和没有结果的工具行动 |
| 错配反馈 | 3 | 非工具行动或同内容新 Action 不能接收原反馈 |
| 同时有反馈和异常 | 1 | 拒绝含义冲突的结果组合 |
| 冻结字段 | 1 | 普通赋值不能改写记录 |

这里的状态和报告均为测试材料；测试通过不证明真实执行和证据可信。
序号是否连续、是否与预算对应、记录是否属于同一个任务，将由记录集合的使用者检查。
本单元不提前实现这些跨步骤规则。

## Run

在项目根目录执行：

```bash
uv run --locked pytest -q tests/test_step_record.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

2026-09-10 已对用户实现运行完整回归：**282 passed in 0.09s**，包含本文件的 **26 个新增用例**。
实际命令为 `uv run --locked --offline --no-cache --no-python-downloads pytest -q`；Ruff lint/format 通过，共 29 个 Python 文件。
记录实现和测试通过 Review，AST 与参考代码一致；助手未修改用户源码或测试。

## Observe

实现后运行下面的观察命令。材料与序号均为手工构造，没有执行工具或模型。
重点观察：给 state 变量赋予新的 TaskState，不会改写旧记录中的历史状态。

```bash
uv run --locked python - <<'PY'
from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.records import StepRecord


state = TaskState(TaskRequest(TaskType.DIAGNOSE, "诊断当前 GEMM"))
state = state.transition_to(TaskStatus.RUNNING)
action = CallToolAction(
    tool_name="read_report",
    arguments={"path": "report.json"},
    reason="读取执行反馈。",
)
observation = ToolObservation(
    action, ToolExecutionStatus.FAILED, "报告文件不存在。"
)
tool_record = StepRecord(1, state, action, observation)

state = state.transition_to(TaskStatus.FAILED)
error_record = StepRecord(2, state, error="model unavailable")

print(tool_record.decision_number)
print(tool_record.action.kind, tool_record.observation.status.value)
print(tool_record.error)
print(error_record.action)
print(error_record.error)
print(error_record.state_after.status.value)
print(tool_record.state_after.status.value)
print(tool_record.state_after.verification.compilation.value)
PY
```

本地手工材料的实际观察输出（2026-09-10）：

```text
1
call_tool failed
None
None
model unavailable
failed
running
not_run
```

第一份记录有失败工具反馈，但没有执行异常；第二份记录只有错误，没有 Action。
最新 state 是 failed，旧 tool_record.state_after 仍是 running。
这展示的是快照保存与结果表达，尚不意味着运行循环会自动创建或保存这些记录。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| True 被当成第 1 次 | 序号测试失败 | bool 是 int 的子类 | 单独拒绝 bool，再检查 int |
| 非法字段导致属性错误 | 类型测试未抛预期错误 | 先访问了 action 字段 | 先校验 Observation 类型，再检查关联 |
| 没有 Action 的模型错误无法记录 | 错误路径测试失败 | 强制每步都有行动 | None + 非空 error 应合法 |
| FAILED 反馈被当作异常 | 工具反馈测试失败 | 混淆返回值与抛错 | Observation 的 FAILED 与 error 分开表达 |
| 同内容新对象被接受 | 错配反馈测试失败 | 使用 == 比较 | 用 is 检查原对象关联 |
| 旧记录状态跟着变化 | Observe 不符合预期 | 修改或覆盖了记录中的状态 | 保存已得到的冻结 TaskState，新状态另行返回并保存 |
| 空记录被接受 | 缺少结果测试失败 | 只校验单个字段类型 | 增加跨字段不变量检查 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位；核心修复由你完成。

## Checkpoint

本单元应理解：当前状态与历史记录的区别、错误发生位置与可用材料、跨字段不变量，以及快照的能力边界。
用户实现与测试已通过 Review：新增 26 个用例随全量 282 个测试通过，lint/format 和快照观察通过；助手未修改源码或测试。
观察时额外断言了原状态快照、行动／反馈引用与 NOT_RUN；没有调用真实模型或工具。

本单元已提交为 `526412f feat: add validated runtime step records`，共 10 个文件；提交后工作区干净。
下一单元见 [运行结果汇总](run-result.md)，由用户实现；有限循环接线保持随后学习单元。
