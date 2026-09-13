# RUN-002E：工具反馈与验证结论

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。统一行动解析入口已提交为
`234282f feat: add validated agent action parser`，进入本单元前工作区干净。
本单元起点为 137 个测试及 lint/format 通过。

我们已有“准备调用哪个工具”的 CallToolAction，现在需要表达“这次调用返回了什么”。
本轮只定义工具反馈 ToolObservation；其他来源的反馈按实际消费需求扩展。
助手准备讲义、专项图和状态文档，核心类和测试由用户输入。
实际进度见 [当前能力与验证范围](status.md)。

## Concept

Action 是行动提议；Observation 是供后续决策使用的执行反馈。

例如，读取服务器回传报告的工具成功返回，但报告记载编译失败。
工具执行状态和算子验证结论必须同时保留：

| 维度 | 这个例子的值 | 回答的问题 |
| --- | --- | --- |
| ToolExecutionStatus | SUCCEEDED | 读取报告的工具是否按协议完成调用？ |
| VerificationState.compilation | FAILED | 报告中给出的编译检查结论是什么？ |
| TaskStatus | 由后续 Runtime 单独维护 | 整个任务现在进行到哪里？ |

compilation 字段保存 VerificationStatus 值。三个维度不能互相推导或混用；
工具 FAILED 也不会自动让任务进入 FAILED。

后续由程序侧工具适配器或执行器根据实际返回值／异常构造 ToolObservation，
Runtime 再决定如何使用它。当前构造函数只验证形式，不证明工具真的执行过或报告有可靠来源。

## Design

| 字段 | 类型与约束 | 用途 |
| --- | --- | --- |
| action | CallToolAction，必须显式提供 | 关联本次尝试所对应的工具提议及稳定参数 |
| status | ToolExecutionStatus，必须显式提供 | SUCCEEDED 或 FAILED，拒绝普通字符串和其他枚举 |
| content | 非空字符串，保留原文 | 工具返回的内容或失败说明 |
| verification | VerificationState 或 None，默认 None | 可选的逐项检查报告，不是整个任务的累计检查状态 |

ToolExecutionStatus.SUCCEEDED 表示调用按工具协议完成并得到可用结果；
FAILED 表示调用未能按协议完成，例如读取失败、超时或返回值不符合工具契约。
这些值由后续执行器归类；本轮不实现调用、超时或错误捕获。

verification 的可选性是本轮的重要设计：

- None：这份反馈没有携带检查报告，不能据此对任何检查下结论。
- VerificationState()：这份反馈携带一份报告，报告的五项检查均明确为 NOT_RUN。
- VerificationState(compilation=FAILED)：报告给出编译失败结论，其余项按报告字段表达。

状态与报告相互独立；不按 SUCCEEDED 自动填 PASSED，也不按 FAILED 清空已有报告。
失败的工具调用可能已经获得部分检查信息，是否可以保留必须基于实际证据。
这里的 NOT_RUN 只描述本份报告，不能覆盖其他报告或 TaskState 的既有结果。

为什么这样设计：

1. 关联已有 CallToolAction，可沿反馈追溯工具名、参数与调用目的，避免复制一套易漂移的字段。
   已有行动是冻结对象，参数是标量值的只读快照，本轮直接保留引用。
2. 单独的枚举区分工具调用、任务生命周期和检查结论，即使字符串值都叫 failed 也不能混用。
3. 复用 VerificationState 表达逐项结果，用 None 避免替没有提供检查结果的工具编造一份报告。
4. frozen 保护本次反馈不被普通字段重新赋值。它不提供数据库事务、证据认证或恶意代码隔离。

content 不是系统指令，后续上下文构建应把工具内容作为数据处理。
工具名和参数只提供提议关联，尚不能区分同一提议的两次执行；
执行／尝试 ID、错误类别、retryable、报告来源和候选版本关联在需要的单元加入。
不把整个任务状态复制进反馈，也不在这里实现报告合并或重试策略。

流程见独立图源 [tool-observation.md](diagrams/tool-observation.md)。
图中的执行器与下一轮决策属于后续集成。

## Implementation

### 文件一：新建 src/kernellens/domain/observation.py

完整输入以下代码，包括导入。两个 class 均放在模块顶层；
这是新文件，不修改 action.py 或 verification.py。

```python
from dataclasses import dataclass
from enum import StrEnum

from kernellens.domain.action import CallToolAction
from kernellens.domain.verification import VerificationState


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolObservation:
    action: CallToolAction
    status: ToolExecutionStatus
    content: str
    verification: VerificationState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, CallToolAction):
            raise TypeError("action must be a CallToolAction")
        if not isinstance(self.status, ToolExecutionStatus):
            raise TypeError("status must be a ToolExecutionStatus")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        if self.verification is not None and not isinstance(
            self.verification, VerificationState
        ):
            raise TypeError("verification must be a VerificationState or None")
```

按逻辑块理解：

1. ToolExecutionStatus 明确描述调用结果；与 TaskStatus、VerificationStatus 分开。
2. ToolObservation 关联已有行动，用可选字段容纳检查报告。
3. __post_init__ 检查 action 和 status 的具体类型，不依赖字符串值相等。
4. content 先判断类型再判空，strip 不赋回字段，保留报告中的换行和格式。
   若工具没有匹配项，反馈应明确写“未找到匹配项”，而不是给一段无法解释的空白。
5. verification 先判断是否为 None，只有提供报告时才检查类型。
   这个判断表达“可缺省，但有值时必须合法”，不会生成或认证检查报告。

### 文件二：新建 tests/test_observation.py

完整参考如下。保留标准库、pytest、项目类型的导入分组。

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import CallToolAction, FinishAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.state import TaskStatus
from kernellens.domain.verification import VerificationState, VerificationStatus


def make_inputs():
    return {
        "action": CallToolAction(
            tool_name="read_verification_report",
            arguments={"path": "reports/compile.json"},
            reason="了解服务器回传的检查结果。",
        ),
        "status": ToolExecutionStatus.SUCCEEDED,
        "content": "  本次工具调用的反馈。\n保留原始格式。  ",
    }


@pytest.mark.parametrize("status", list(ToolExecutionStatus))
def test_preserves_feedback_without_a_verification_report(status):
    inputs = make_inputs()
    inputs["status"] = status

    observation = ToolObservation(**inputs)

    assert observation.action is inputs["action"]
    assert observation.status is status
    assert observation.content == inputs["content"]
    assert observation.verification is None


def test_successful_tool_can_report_failed_compilation():
    inputs = make_inputs()
    inputs["content"] = "读取报告成功；报告记录编译失败。"
    checks = VerificationState(compilation=VerificationStatus.FAILED)

    observation = ToolObservation(**inputs, verification=checks)

    assert observation.status is ToolExecutionStatus.SUCCEEDED
    assert observation.verification is checks
    assert observation.verification.compilation is VerificationStatus.FAILED


def test_missing_report_differs_from_checks_not_run():
    inputs = make_inputs()
    checks = VerificationState()

    without_report = ToolObservation(**inputs)
    with_report = ToolObservation(**inputs, verification=checks)

    assert without_report.verification is None
    assert with_report.verification is checks
    assert with_report.verification.compilation is VerificationStatus.NOT_RUN


@pytest.mark.parametrize(
    "name, value",
    [
        ("action", None),
        ("action", FinishAction(answer="交付说明。", reason="准备提交。")),
        ("status", "succeeded"),
        ("status", TaskStatus.FAILED),
        ("status", VerificationStatus.FAILED),
        ("content", None),
        ("content", True),
        ("verification", {}),
        ("verification", VerificationStatus.PASSED),
    ],
)
def test_rejects_invalid_field_types(name, value):
    inputs = make_inputs()
    inputs[name] = value

    with pytest.raises(TypeError, match=name):
        ToolObservation(**inputs)


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_rejects_blank_feedback(content):
    inputs = make_inputs()
    inputs["content"] = content

    with pytest.raises(ValueError, match="content"):
        ToolObservation(**inputs)


def test_feedback_status_cannot_be_rewritten():
    observation = ToolObservation(**make_inputs())

    with pytest.raises(FrozenInstanceError):
        observation.status = ToolExecutionStatus.FAILED
```

make_inputs 每次构造一份新的有效输入，测试只替换需要检查的字段。
工具名 read_verification_report 和路径 reports/compile.json 都是手写测试数据，
不表示工具已经注册、文件存在或发生过读取。

6 个测试函数展开为 16 个用例：

- 两种调用状态下，原行动、内容与缺省报告被保留：2 个。
- 工具成功与报告中的编译失败可以同时存在：1 个。
- 缺少报告与明确未运行不同：1 个。
- 错误行动、字符串／其他枚举状态、错误内容和报告类型被拒绝：9 个。
- 空白内容被拒绝：2 个。
- 已记录的调用状态不能普通重新赋值：1 个。

不通过这些测试宣称报告属实或算子检查通过；这里验证反馈的数据契约。

## Run

保存两个文件后，在项目根执行：

```bash
uv run --locked pytest -q tests/test_observation.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期专项为 16 passed；全量测试为 153 个（原有 137 + 新增 16）。
用户实现已验收，全量实测 153 passed，lint/format 通过；最新记录以 docs/status.md 为准。
如有排版问题，按提示整理对应文件后复查。

## Observe

运行 `uv run --locked python` 后逐行输入以下手写样例：

```python
from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.domain.verification import VerificationState, VerificationStatus

action = CallToolAction(
    tool_name="read_verification_report",
    arguments={"path": "reports/compile.json"},
    reason="了解服务器回传的检查结果。",
)
observation = ToolObservation(
    action=action,
    status=ToolExecutionStatus.SUCCEEDED,
    content="读取报告成功；报告记录编译失败。",
    verification=VerificationState(compilation=VerificationStatus.FAILED),
)
print(observation.status.value)
assert observation.verification is not None
print(observation.verification.compilation.value)
print(observation.action is action)
```

预期依次为 succeeded、failed、True。
同一份反馈既记录工具成功，也保留编译失败，并关联原来的行动提议。
这里用 assert 明确报告存在，之后才读取 compilation。

继续输入：

```python
without_report = ToolObservation(
    action=action,
    status=ToolExecutionStatus.FAILED,
    content="无法读取回传报告，因此没有可用的检查结论。",
)
print(without_report.verification)
```

预期 None。无法取得报告并不等于编译检查 FAILED。
整个例子只是构造对象，没有读取文件、连接服务器或执行 GPU 检查。用 exit() 退出解释器。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入 ToolObservation | ModuleNotFoundError 或 ImportError | 文件位置、保存状态或类作用域不正确 | 核对 observation.py 在 domain 内，类名准确且顶格 |
| 合法的 None 报告被拒绝 | 缺省报告用例 TypeError | 未先排除 None 就检查 VerificationState | 使用 is not None 与 isinstance 的组合 |
| 字符串或其他 FAILED 枚举被接受 | 错误状态用例没有抛异常 | 只比较了字符串值 | 使用 isinstance(status, ToolExecutionStatus) |
| 工具成功使编译自动变成通过 | 成功调用／失败检查组合用例失败 | 从执行状态推导了检查结论 | 保留调用者提供的验证报告，不自动改写 |
| 缺少报告被变成 NOT_RUN | 缺省报告断言失败 | 使用 default_factory 自动创建报告 | verification 默认 None，明确区分缺失和报告中的结果 |
| 读取 compilation 报 AttributeError | verification 为 None | 没先确认这份反馈有检查报告 | 显式处理无报告分支后再读取检查字段 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。

## Checkpoint

本单元目标：把工具反馈建模为可关联、可校验的对象，区分调用状态与业务检查结论，
理解“没有报告”与“报告明确未运行”的差别。它为后续 Runtime 接收反馈和决定下一步提供契约，
本轮尚未形成执行闭环。

用户实现已通过 Review：153 个测试、lint/format 与运行观察通过；已由用户提交为 `a9588d2 feat: add tool observation contract`，包括反馈模型、测试、讲义、专项图与相关状态文档。提交及干净工作区已核对。
本单元未创建执行器、模型适配器或 Runtime。当前学习进度见 [当前能力与验证范围](status.md)。
