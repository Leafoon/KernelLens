# RUN-001A：定义任务请求

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 1 已由用户提交为 `9516488 feat: add validated application settings`。
当前进入 Phase 2 — State & Minimal Runtime。本单元只定义任务请求，属于 RUN-001 的第一个学习单元。
本文给出参考代码；实际实现与检查状态见 [当前能力与验证范围](status.md)。

## Concept

Agent 需要知道用户希望完成什么。先把三种业务目标表达成统一对象，后续 Runtime 才能接收明确的输入。

- `TaskType`：生成、优化或诊断，由调用者明确选择；本轮不做自然语言意图分类。
- `TaskRequest`：保存任务类型与用户原始目标，是领域模型，即代码中对业务概念及规则的表达。
- 不变量：任何成功创建的请求都具有合法类型和非空文本；普通字段赋值不能改写原始目标。

任务请求表达“想做什么”；后续 State 表达“进行到哪里”。这两个概念会一起参与 Runtime，但本轮只实现前者。
接收请求不表示已经有足够信息生成算子。例如用户尚未给出 shape，仍可创建请求，后续需求检查应识别缺口并请求补充。

## Design

位置：调用者 → TaskRequest 的创建与校验 → 后续的任务执行入口。

| 项目 | 当前契约 |
| --- | --- |
| 输入接口 | `TaskRequest(task_type: TaskType, goal: str)` |
| 任务类型 | `generate`、`optimize`、`diagnose`；内部必须传入 TaskType 成员 |
| 目标 | 非空字符串；空字符串和纯空白拒绝；接受后保留原文 |
| 类型不符 | TypeError，指出对应字段 |
| 目标为空 | ValueError，指出 goal |
| 输出 | 可读取且禁止常规字段重新赋值的 TaskRequest |
| 副作用 | 无文件访问、环境读取、模型调用或算子执行 |
| 验收范围 | 检查基本输入形式；不判断 shape、设备、权限或证据是否齐备 |

两个字段已经足以给下一个状态单元提供任务目标。shape、dtype、附件和设备的结构化契约，到产品需求检查单元再细化。
请求中不加入 run ID、预算或执行结果：这些属于后续运行状态。

继续使用当前 Python 3.12 的标准库 `dataclass` 和 `StrEnum`，不增加依赖。
字典虽然能存储两个值，但容易漏字段或混入未知类型；显式类与构造校验集中表达规则。
当前校验很少，手写可以观察类型标注与运行时校验的区别；模型、工具等外部结构化输入变复杂时再评估 Pydantic。

## Implementation

助手只创建 `src/kernellens/domain/__init__.py`，其中只有包说明。下面两个文件由用户亲手创建。
已有 `src/kernellens` 是包目录，不要在其中再嵌套同名的 kernellens 目录。

### 文件一：src/kernellens/domain/task.py

```python
from dataclasses import dataclass
from enum import StrEnum


class TaskType(StrEnum):
    GENERATE = "generate"
    OPTIMIZE = "optimize"
    DIAGNOSE = "diagnose"


@dataclass(frozen=True)
class TaskRequest:
    task_type: TaskType
    goal: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_type, TaskType):
            raise TypeError("task_type must be a TaskType")
        if not isinstance(self.goal, str):
            raise TypeError("goal must be a string")
        if not self.goal.strip():
            raise ValueError("goal must not be blank")
```

逻辑块说明：

1. `StrEnum` 为三种任务建立固定名字和字符串值，避免到处拼写字符串。`TaskType("generate")` 可显式将外部字符串转成成员；未知值会报错。
2. `dataclass` 生成初始化与表示方法，`frozen=True` 禁止普通字段赋值。运行期间的进展另存 State，保持原始请求可追踪。
3. `__post_init__` 在 dataclass 生成的初始化方法设置字段后自动调用，校验不通过就抛出异常，调用者拿不到成功构造的请求。
4. Python 类型标注本身不检查运行时输入，所以分别检查类型，再调用字符串方法。否则 None 可能产生难理解的 AttributeError。
5. `strip()` 仅用于判空；没有把结果赋回 goal，因此会保留目标原文中的格式。

### 文件二：tests/test_task.py

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.task import TaskRequest, TaskType


@pytest.mark.parametrize("task_type", list(TaskType))
def test_accepts_task_types_and_preserves_goal(task_type):
    goal = "  处理这个 GEMM 算子需求\n"

    request = TaskRequest(task_type=task_type, goal=goal)

    assert request.task_type is task_type
    assert request.goal == goal


@pytest.mark.parametrize("goal", ["", " \n\t"])
def test_rejects_blank_goal(goal):
    with pytest.raises(ValueError, match="goal"):
        TaskRequest(task_type=TaskType.GENERATE, goal=goal)


def test_rejects_raw_task_type_string():
    with pytest.raises(TypeError, match="task_type"):
        TaskRequest(task_type="generate", goal="生成 GEMM")


def test_rejects_non_string_goal():
    with pytest.raises(TypeError, match="goal"):
        TaskRequest(task_type=TaskType.GENERATE, goal=None)


def test_original_goal_cannot_be_reassigned():
    request = TaskRequest(task_type=TaskType.GENERATE, goal="生成 GEMM")

    with pytest.raises(FrozenInstanceError):
        request.goal = "改为诊断"
```

这些断言覆盖允许的三种任务、原文保留、无效输入拒绝和原始目标不能被直接改写。
测试故意传入字符串类型和 None，观察注解不会自动拦截输入，真正拦截它们的是构造校验。
5 个测试函数产生 8 个用例：第一个参数化为 3 个，第二个为 2 个，其余各 1 个。
暂时延续已有 tests 的平铺结构，出现不同测试层次后再整理。

## Run

保存两个文件后，在项目根运行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期共 `12 passed`：已有 4 个配置测试，加上本单元的 8 个用例。实际验收结果以 [当前能力与验证范围](status.md) 为准。
格式问题可用 `uv run --locked ruff format src tests` 处理，再阅读并检查结果。

## Observe

运行 `uv run --locked python`，在交互式 Python 中逐行输入：

```python
from kernellens.domain.task import TaskRequest, TaskType
request = TaskRequest(task_type=TaskType.GENERATE, goal="生成一个 GEMM 算子")
print(request.task_type.value)
print(request.goal)
TaskRequest(task_type=TaskType.GENERATE, goal="   ")
```

前两次打印应为 `generate` 与 `生成一个 GEMM 算子`；最后一行应抛出 `ValueError: goal must not be blank`。
这次异常是预期的拒绝行为：非法请求在进入未来 Runtime 前就被拦截。
用 `exit()` 退出 Python。你现在观察到的是对象创建与校验，尚未执行 Agent 或生成算子。

## Debug

| Problem | Evidence | Hypothesis | Verification / Fix |
| --- | --- | --- | --- |
| 无法导入 task | ModuleNotFoundError | 保存位置或文件名不符 | 确认 src/kernellens/domain/task.py；通过 uv run 运行 |
| 非空请求也报 TypeError | 错误指出 task_type | 传入了普通字符串 | 内部使用 TaskType.GENERATE；外部字符串在入口显式转换，不默认猜测类型 |
| 空目标未报错 | DID NOT RAISE | 校验方法没有被调用 | 检查 __post_init__ 两侧双下划线及类内缩进 |
| None 引发 AttributeError | 报错指向 strip | 在检查类型前调用了字符串方法 | 先验证类型，再做判空 |
| 原文对比失败 | assert request.goal 的差异 | 归一化改写了用户原文 | strip 仅用于判空，不赋回原字段 |

保持 Problem → Evidence → Hypothesis → Verification → Fix。保留失败输出，先核对实现，不用修改测试期望来掩盖问题。

## Checkpoint

用户完成输入与运行后回复“已完成”或“帮我检查”；助手先读取真实代码，再 Review 与验证，期间不创建 State 或 Runtime。
通过验收后，本单元可独立提交为 `feat: add task request contract`，包含领域包、请求、测试和相关文档；提交前审阅暂存范围，提交后再确认下一学习单元。
学习目标：领域模型、不变量、枚举、构造校验、保留原始目标，以及任务请求与运行状态的职责区别。
