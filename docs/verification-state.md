# RUN-001C：逐项记录验证状态

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。生命周期单元已由用户提交为 `cc6fbdb feat: add task lifecycle transitions`；本单元开始前，应用验收为 51 个测试通过。
本轮实现验证状态的表达契约；完整 TaskState 和实际检查工具后续再做。本文给出参考代码，真实完成情况以 [当前能力与验证范围](status.md) 为准。

## Concept

TaskStatus 回答“任务进行到哪里”，VerificationStatus 回答“某一项检查得到了什么结果”。
例如用户要求生成代码和运行说明，交付完成时可能已经检查语法与 API 依据，但 GPU 编译、正确性和性能仍未执行。

| 验证状态 | 含义 | 示例 |
| --- | --- | --- |
| NOT_RUN / not_run | 该检查尚未执行 | 代码尚未移交 GPU 服务器编译 |
| PASSED / passed | 针对该检查及其范围，有证据支持通过 | 当前候选通过指定语法检查 |
| FAILED / failed | 针对该检查，有证据支持未通过 | 编译器明确报告当前候选的编译错误 |
| INCONCLUSIVE / inconclusive | 已尝试检查，但结果不足以可靠判断通过或失败 | 收到的执行日志截断，无法确定检查结论 |

缺少 GPU 导致编译根本未启动时应为 NOT_RUN；已经尝试检查但结论不可靠时为 INCONCLUSIVE。
单个 True/False 无法清楚表达四种含义。本轮也不生成“整体已验证”的布尔值，避免把不同检查合并成一个模糊结论。

## Design

独立示例图见 [verification-state.md](diagrams/verification-state.md)。

| 字段 | 表达的检查 | 默认值 |
| --- | --- | --- |
| syntax | 源码语法 | NOT_RUN |
| api_evidence | 所用 API 与当前源码依据是否匹配 | NOT_RUN |
| compilation | 目标环境中的编译 | NOT_RUN |
| correctness | 指定工作负载、参考结果和容差下的数值正确性 | NOT_RUN |
| performance | 指定基线和可比较条件下是否满足性能目标 | NOT_RUN |

接口是 `VerificationState(...)`，五个字段均接收 VerificationStatus，可省略并使用 NOT_RUN。
只传入部分结果时，其他字段维持 NOT_RUN；语法通过不会使编译或正确性自动通过。
输出是禁止常规字段重新赋值的结果快照。字段类型不符则抛 TypeError，错误指出字段名。

这里先存检查结论；来源、候选标识、环境、工作负载和原始证据会在 Evidence / VerificationRecord 单元补齐。
构造函数只校验状态类型，不读取证据、不执行检查，也不能证明调用者填写的 PASSED 是真实的。后续工具和报告验收模块负责依据证据设置与核对结果。
例如编译器正常返回“编译失败”，工具调用可以成功而 compilation 为 FAILED；两者不能用同一字段代替。

继续使用现有标准库 dataclass 与 StrEnum，不引入新依赖。独立文件保持验证语义与生命周期语义分开，后续 TaskState 再组合它们。
这些固定、不可变的枚举值可以直接作为默认值；本轮没有共享可变列表或字典。

## Implementation

两个文件都由用户亲手创建，助手只保存讲义、图与状态文档。

### 文件一：src/kernellens/domain/verification.py

```python
from dataclasses import dataclass, fields
from enum import StrEnum


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class VerificationState:
    syntax: VerificationStatus = VerificationStatus.NOT_RUN
    api_evidence: VerificationStatus = VerificationStatus.NOT_RUN
    compilation: VerificationStatus = VerificationStatus.NOT_RUN
    correctness: VerificationStatus = VerificationStatus.NOT_RUN
    performance: VerificationStatus = VerificationStatus.NOT_RUN

    def __post_init__(self) -> None:
        for field in fields(self):
            if not isinstance(getattr(self, field.name), VerificationStatus):
                raise TypeError(f"{field.name} must be a VerificationStatus")
```

按逻辑块理解：

1. VerificationStatus 定义四种检查结论，与 TaskStatus 的生命周期名称分开。
2. 每个字段独立默认 NOT_RUN。省略字段代表未执行，不能被解释成通过。
3. frozen=True 禁止普通字段赋值，保存一个明确的结果快照。以后记录新结果时应显式生成新快照，并保留对应证据。
4. 新接触的 `fields(self)` 返回 dataclass 字段的描述；`field.name` 是字段名，`getattr(self, field.name)` 按名字取实际值，例如 getattr(self, "syntax") 等价于 self.syntax。
5. 循环统一执行五次类型检查，避免复制五段校验。错误仍保留具体字段名。

StrEnum 的字符串行为不能替代类型检查。TaskStatus.FAILED 与 VerificationStatus.FAILED 的字符串值同为 failed，代表的业务含义却不同；不能把前者存进验证字段。
同样，不使用 `if checks.compilation:` 判断通过。非空字符串值包括 failed 和 not_run 都具有真值；应明确比较 `checks.compilation is VerificationStatus.PASSED`。

### 文件二：tests/test_verification.py

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskStatus
from kernellens.domain.verification import VerificationState, VerificationStatus


@pytest.mark.parametrize(
    "check_name",
    ["syntax", "api_evidence", "compilation", "correctness", "performance"],
)
def test_new_checks_start_as_not_run(check_name):
    checks = VerificationState()

    assert getattr(checks, check_name) is VerificationStatus.NOT_RUN


def test_checks_can_have_different_outcomes():
    checks = VerificationState(
        syntax=VerificationStatus.PASSED,
        api_evidence=VerificationStatus.INCONCLUSIVE,
        compilation=VerificationStatus.FAILED,
    )

    assert checks.syntax is VerificationStatus.PASSED
    assert checks.api_evidence is VerificationStatus.INCONCLUSIVE
    assert checks.compilation is VerificationStatus.FAILED
    assert checks.correctness is VerificationStatus.NOT_RUN
    assert checks.performance is VerificationStatus.NOT_RUN


@pytest.mark.parametrize("value", ["passed", TaskStatus.FAILED, None, True])
def test_rejects_values_from_wrong_type(value):
    with pytest.raises(TypeError, match="compilation"):
        VerificationState(compilation=value)


def test_snapshot_cannot_be_rewritten():
    checks = VerificationState()

    with pytest.raises(FrozenInstanceError):
        checks.syntax = VerificationStatus.PASSED
```

四个测试函数展开为 11 个用例：默认状态 5 个、混合结果 1 个、错误类型 4 个、快照保护 1 个。
它们保护的业务不变量是：未执行不能默认通过，各检查独立，生命周期状态不能混入检查结论。
测试使用人为指定的枚举值，不执行算子，也不能证明任何真实算子已经通过检查。

## Run

保存文件后，在项目根执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期 62 passed：已有 51 个，加上本轮 11 个。这里是实现后的验收目标，当前实际结果见 docs/status.md。
若只有排版问题，运行 `uv run --locked ruff format src tests` 后查看变化并复查。

## Observe

运行 `uv run --locked python`，逐行输入：

```python
from kernellens.domain.state import TaskStatus
from kernellens.domain.verification import VerificationState, VerificationStatus
checks = VerificationState()
print(checks.compilation.value)
checks = VerificationState(
    syntax=VerificationStatus.PASSED,
    api_evidence=VerificationStatus.PASSED,
)
print(checks.syntax.value)
print(checks.compilation.value)
print(checks.correctness.value)
VerificationState(compilation=TaskStatus.FAILED)
```

四次打印依次为 not_run、passed、not_run、not_run。最后一行应抛出 `TypeError: compilation must be a VerificationStatus`。
观察语法通过没有传播成编译或正确性通过；相同的 failed 字符串也不能让不同业务枚举混用。用 exit() 退出 Python。
本单元尚未组合 TaskStatus 与 VerificationState；任务完成时不改写检查结果的集成行为，到 TaskState / Runtime 单元再测试。

## Debug

| Problem | Evidence | Hypothesis | Verification / Fix |
| --- | --- | --- | --- |
| 默认检查成为 PASSED | 默认值断言失败 | 字段默认值误写 | 对照五个字段的 NOT_RUN，不改测试期望 |
| 枚举混用未被拒绝 | DID NOT RAISE | 使用字符串相等或遗漏构造校验 | 检查 __post_init__ 与 isinstance 的枚举类 |
| 错误指出所有输入都非法 | 默认创建也失败 | 校验了字段描述而非字段值 | fields 给出描述，需用 getattr 读取实际值 |
| FAILED 被当作通过 | 分支使用 if checks.compilation | 把字符串真值当成通过判断 | 明确比较 VerificationStatus.PASSED |
| 无法导入 verification | ModuleNotFoundError | 路径或保存错误 | 确认 src/kernellens/domain/verification.py，通过 uv run 运行 |

保持 Problem → Evidence → Hypothesis → Verification → Fix。出现失败先保留输出，由用户修改核心逻辑后再验收。

## Checkpoint

本轮目标是掌握任务生命周期与验证状态的区别、保守默认值、逐项结论和枚举类型边界。
完成输入与运行后回复“已完成”或“帮我检查”；助手先 Review 实际文件，再验收，不提前创建完整 TaskState、证据管理或 Runtime。
验收后建议提交 `feat: add per-check verification state`，包含验证契约、测试、讲义、专项图和相关文档；提交前审阅暂存范围，实际验收与提交状态见 docs/status.md。
