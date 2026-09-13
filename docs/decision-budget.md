# RUN-003B：决策次数预算与明确停止

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。RUN-003A 已提交为
`403c05b feat: add validated runtime decision step`，进入本单元前工作区干净。
最近一次完整验收为 171 个测试及 lint/format 通过。

decide_once 已能完成一次决策，但未来循环不能无限调用它。
本单元只实现决策次数预算：一次申请消耗一个额度，到达上限后明确拒绝。
循环、行动分派与生命周期更新在后续单元串联。
实际进度见 [当前能力与验证范围](status.md)。

## Concept

**次数预算**限制的是允许开始多少次决策尝试。模型返回无效内容或调用失败，也不能免费重试。
因此调用者应先检查运行入口、取得新预算快照，再开始决策；不能等得到合法行动后才计数。

这里 used_decisions 表示已经消耗的决策额度，不是 Provider 的实际请求数。
消耗额度不证明模型已经调用，单次 SDK 调用也可能在内部重试；Token、费用和耗时另行计量。
本轮不会把本地测试产生的数字写成真实模型用量。

**为什么用一个小对象？** 把上限、用量和递增规则集中起来，可以独立测试越界，
避免把判断散落在未来循环的多个分支中。只在循环中使用 range 也能限制最简单循环；
当我们需要显式返回剩余额度、处理失败和等待后继续时，预算快照更便于传递。
现在一个标准库 dataclass 足够，不需要数据库、Redis 或调度框架。

**为什么自定义异常？** ValueError 表示预算配置不合法；
DecisionBudgetExhausted 表示一个合法预算已正常用尽。后续 Runtime 可以精确捕获后者，
把任务转为 BUDGET_EXHAUSTED，而不是把所有 ValueError 都当成额度耗尽。
当前对象自身不更新 TaskState，也没有实现这个捕获流程。

## Design

| 字段／接口 | 契约 | 含义 |
| --- | --- | --- |
| max_decisions | 正整数，拒绝 bool | 本次运行允许消耗的决策额度上限 |
| used_decisions | 整数，0 到上限，默认 0，拒绝 bool | 已消耗额度；等于上限是合法的耗尽快照 |
| consume() | 返回新的 DecisionBudget | 有额度时加一，原快照不变 |
| DecisionBudgetExhausted | 独立的 RuntimeError 子类 | 无额度时抛出，不产生越界快照 |

保持不变量：`0 <= used_decisions <= max_decisions`。
预算为 2 时，第一次和第二次 consume 成功，第三次失败。
“允许最后一次”与“最后一次之后拒绝”是本步需要测试的边界。

专项图见 [决策预算流程](diagrams/decision-budget.md)，可独立 Markdown 预览。

预算属于 Runtime 控制信息，不放进 TaskRequest，也不改写上一单元的 decide_once。
未来运行层负责沿用最新快照、在调用前检查额度、在耗尽时停止。
当前对象不能防止调用者忽略新快照、每轮重建预算或直接绕过它；
单元实现完成不等于完整 Agent 已经具备防无限循环能力。
本轮也不解决执行超时、并发计数、持久化或恢复后的预算校验。

## Implementation

助手只准备本文、独立图源与相关状态文档。本轮不新增依赖，也不修改现有核心代码。

### 1. 预算模型

由用户创建 `src/kernellens/runtime/budget.py` 并输入：

```python
from dataclasses import dataclass, replace


class DecisionBudgetExhausted(RuntimeError):
    """Raised when no decision allowance remains."""


@dataclass(frozen=True)
class DecisionBudget:
    max_decisions: int
    used_decisions: int = 0

    def __post_init__(self) -> None:
        for name in ("max_decisions", "used_decisions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer, not bool")
        if self.max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        if not 0 <= self.used_decisions <= self.max_decisions:
            raise ValueError("used_decisions must be between 0 and max_decisions")

    def consume(self) -> "DecisionBudget":
        if self.used_decisions >= self.max_decisions:
            raise DecisionBudgetExhausted("decision budget exhausted")
        return replace(self, used_decisions=self.used_decisions + 1)
```

按逻辑块理解：

1. 自定义异常没有额外字段；它提供可被后续 Runtime 精确识别的停止信号。
2. frozen 与此前 TaskState 相同，阻止常规字段赋值。consume 使用 replace 构造新快照。
3. 先检查两个字段的类型，再比较范围。Python 中 `isinstance(True, int)` 为 True，
   所以额度计数需要单独拒绝 bool，不能把 True 当作一次额度。
4. used_decisions 等于上限时允许构造，表示一个已耗尽的有效状态；
   超过上限则拒绝，不能通过 min/max 静默纠正输入。
5. consume 先检查再递增。调用方必须写 `budget = budget.consume()`，
   只写 `budget.consume()` 会丢弃返回的新快照。
6. 调用方已经接收新快照后，下游模型异常不会把变量自动退回旧值。
   这里不提供自动退款；失败尝试同样占用一次额度。

### 2. 预算边界测试

由用户创建 `tests/test_decision_budget.py`。共 7 个测试函数，参数化后 19 个用例。

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
from kernellens.runtime.budget import DecisionBudget, DecisionBudgetExhausted
from kernellens.runtime.step import decide_once


def test_consume_returns_a_new_budget_snapshot():
    original = DecisionBudget(max_decisions=2)

    updated = original.consume()

    assert original.used_decisions == 0
    assert updated.used_decisions == 1
    assert updated.max_decisions == 2
    assert updated is not original


def test_allows_exactly_the_configured_number_of_attempts():
    budget = DecisionBudget(max_decisions=2)

    for expected in (1, 2):
        budget = budget.consume()
        assert budget.used_decisions == expected

    for _ in range(2):
        with pytest.raises(DecisionBudgetExhausted):
            budget = budget.consume()
        assert budget.used_decisions == 2


@pytest.mark.parametrize("field", ["max_decisions", "used_decisions"])
@pytest.mark.parametrize("value", [True, False, 1.5, "2", None])
def test_rejects_non_integer_budget_fields(field, value):
    values = {"max_decisions": 2, "used_decisions": 0}
    values[field] = value

    with pytest.raises(TypeError, match=field):
        DecisionBudget(**values)


@pytest.mark.parametrize("limit", [0, -1])
def test_rejects_non_positive_limits(limit):
    with pytest.raises(ValueError, match="max_decisions"):
        DecisionBudget(max_decisions=limit)


@pytest.mark.parametrize("used", [-1, 3])
def test_rejects_usage_outside_the_limit(used):
    with pytest.raises(ValueError, match="used_decisions"):
        DecisionBudget(max_decisions=2, used_decisions=used)


@pytest.mark.parametrize("field", ["max_decisions", "used_decisions"])
def test_budget_fields_are_frozen(field):
    budget = DecisionBudget(max_decisions=2)

    with pytest.raises(FrozenInstanceError):
        setattr(budget, field, 0)


def test_model_failure_does_not_refund_consumed_budget():
    state = TaskState(
        TaskRequest(TaskType.DIAGNOSE, "诊断 GEMM 编译失败"),
        status=TaskStatus.RUNNING,
    )
    budget = DecisionBudget(max_decisions=1)
    calls = []

    def failing_model(received_state, observations):
        calls.append(received_state)
        raise RuntimeError("model unavailable")

    budget = budget.consume()
    with pytest.raises(RuntimeError, match="model unavailable"):
        decide_once(state, failing_model)

    assert budget.used_decisions == 1
    assert len(calls) == 1
    assert state.status is TaskStatus.RUNNING

    with pytest.raises(DecisionBudgetExhausted):
        budget = budget.consume()
        decide_once(state, failing_model)
    assert len(calls) == 1
```

这些测试关注三类可观察行为：

- 额度边界：允许恰好两次，耗尽后再次申请仍然拒绝。
- 数据边界：拒绝 bool、其他错误类型、非正上限和越界用量；正常字段不能直接重写。
- 调用顺序：手动组合 consume 与现有 decide_once，用一个抛异常的模型替身说明失败不退款。
  下一次 consume 抛错后，同一代码块中的模型调用不会执行。

最后一个测试只验证这段显式组合顺序，不代表 decide_once 已自动接入预算。
它保留了 RUNNING 状态；未来 Runtime 才负责在捕获耗尽信号后更新任务。

## Run

在本项目根目录执行：

```bash
uv run --locked pytest -q tests/test_decision_budget.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

新测试预期 **19 passed**。完整回归命令为 `uv run --locked pytest -q`，
本单元正确且没有其他变更时预期 **190 passed**。
这些是预期结果，实际验收在用户输入后执行；参考代码静态检查不能代替应用测试。

## Observe

实现后，在项目根目录执行下面整段命令：

```bash
uv run --locked python - <<'PY'
from kernellens.runtime.budget import DecisionBudget, DecisionBudgetExhausted

budget = DecisionBudget(max_decisions=2)
initial = budget

for _ in range(2):
    budget = budget.consume()
    print(budget.used_decisions)

try:
    budget = budget.consume()
except DecisionBudgetExhausted as error:
    print(error)

print(initial.used_decisions)
print(budget.used_decisions)
PY
```

预期：

```text
1
2
decision budget exhausted
0
2
```

第三次 consume 抛错时，赋值不会发生，因此 budget 仍指向已消耗 2 次的快照。
initial 仍指向原来的 0 次快照。这段演示没有调用模型或执行工具。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入预算类 | ModuleNotFoundError / ImportError | 文件位置、名称或类作用域有误 | 核对 runtime/budget.py，两个类均在模块顶层 |
| True 被接受为额度 | 类型边界测试未抛异常 | 只使用 isinstance(value, int) | 验证 isinstance(True, int)，再显式拒绝 bool |
| 第二次就拒绝两次预算 | 边界测试失败 | 检查条件提前减一 | 在递增前比较当前用量是否已达到上限 |
| 用量始终是 0 | 原对象保持未使用 | 没有接收 consume 返回值 | 使用 budget = budget.consume() |
| 模型失败后没有计数 | 失败调用测试用量为 0 | 把 consume 放到了决策成功之后 | 在执行前接收新预算快照，再调用 decide_once |
| 异常后仍然调用模型 | calls 长度超过 1 | 捕获耗尽后无条件继续 | 看异常与后续调用是否在同一受控流程；耗尽路径应退出或停止 |
| TaskStatus 没有变化 | 仍为 RUNNING | 误以为预算类负责整个生命周期 | 这是当前契约；状态更新留给后续运行层 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。

## Checkpoint

本单元要学会：把“必须停止”变成明确的程序规则，区分额度耗尽与配置错误，
理解边界计数、不可变预算和失败尝试的额度消耗顺序。

用户实现已通过 Review：190 个测试（含本单元 19 个用例）、lint/format 与运行观察通过。
助手只补齐 budget.py 的末尾换行，前后 AST 一致；核心逻辑及测试由用户完成。
实际观察为：前两次 consume 成功，第三次耗尽；原快照为 0，最新快照为 2。

已由用户提交为 `76dd78d feat: add decision attempt budget`，
包含预算模型、边界测试与配套文档；实际提交及干净工作区已核对。
本单元未接入运行循环。当前进度见 [当前能力与验证范围](status.md)。
