# RUN-002C：结果提交提议与行动联合类型

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

Phase 2 — State & Minimal Runtime。工具调用提议已提交为 `49fff51 feat: add tool call action with argument snapshots`，开始本单元前工作区干净；最近一次应用验收为 105 个测试通过。
本轮定义 FinishAction，并用 AgentAction 表达三种行动的联合类型。参考代码和测试由用户输入，实际状态见 [当前能力与验证范围](status.md)。

## Concept

Agent 除了请求信息和调用工具，还需要提出“我准备提交这份结果”。这就是 FinishAction。

| 对象 | 表达什么 | 谁负责决定 |
| --- | --- | --- |
| FinishAction | 准备提交的结果及提交理由 | 先由测试代码构造，后续可由模型提出 |
| TaskStatus.COMPLETED | 任务的交付已满足完成条件 | 后续 Runtime 根据程序验收结果更新 |
| VerificationState | 编译、正确性、性能等具体检查的结论 | 根据相应证据逐项记录 |

模型给出完成理由不等于程序验收通过。名称中的 Finish 表示结束提议，本对象没有结束任务的方法。
构造它只检查数据形式；既不证明答案正确，也不证明候选、源码引用或执行证据存在。

## Design

| 字段 | 契约 |
| --- | --- |
| answer | 待提交的非空结果文本，保留原文，包括换行与代码缩进 |
| reason | 非空提交理由，说明为什么现在提出交付，保留原文 |
| kind | 固定为 finish，不接收构造参数覆盖 |

非字符串字段抛 TypeError；空白字段抛 ValueError；对象禁止普通字段重新赋值。
answer 与 reason 都必须显式提供，不把一句“已完成”或空文本设为默认交付。

第一版只保存文本，为之后的最小循环提供明确结束提议。候选产物、证据引用及结构化报告会在相应单元接入，不在这里提前构造尚无来源的证据 ID。
也不在行动中添加 status=completed、verified=True 等字段，让模型提交的文本覆盖程序维护的生命周期或检查状态。

三种行动的数据用途不同，继续保留三个独立类，用联合类型声明它们共同属于 AgentAction：

```text
RequestInputAction  → question + reason
CallToolAction      → tool_name + arguments + reason
FinishAction        → answer + reason
```

联合类型表示“一次行动是其中一种”。它不代表一次同时执行三种行动，也不是三个类的共同父类。
完整边界图见 [finish-action.md](diagrams/finish-action.md)。图中的业务验收、完成转换与拒绝反馈均为后续集成方向。

继续使用现有标准库和项目 Python 3.12，不新增依赖、模块目录或基类。现有 parse_request_input_action 仍只解析补充信息行动；通用解析入口在三类契约就绪后单独实现。

## Implementation

### 文件一：修改 src/kernellens/domain/action.py

保留现有导入、两个行动类及补充信息 Parser，在文件末尾追加：

```python
@dataclass(frozen=True)
class FinishAction:
    answer: str
    reason: str
    kind: Literal["finish"] = field(default="finish", init=False)

    def __post_init__(self) -> None:
        for name in ("answer", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must not be blank")


type AgentAction = RequestInputAction | CallToolAction | FinishAction
```

按逻辑块理解：

1. answer 是待交付内容；reason 是提出交付的理由。理由不能代替答案，也不自动成为验收证据。
2. fixed kind、构造校验与 frozen 使用已有做法。strip 仅用于判空，不对 answer 赋回处理后的文本，以免破坏格式。
3. 这里没有 TaskState 参数，也不导入生命周期或验证模型；创建提议不负责完成转换。
4. `type AgentAction = ...` 使用项目 Python 3.12 的类型别名语法，竖线表示联合。这一行必须放在模块顶层，行首没有缩进；缩进到 FinishAction 内部会创建类作用域别名，模块级导入将失败。之后的模型接口与解析入口可以用 AgentAction 标注返回值，明确允许的行动种类。
5. AgentAction 是类型别名，不是构造器。使用 FinishAction(...) 等具体类创建对象；也不要把这个别名当作运行时校验器或用于 isinstance(value, AgentAction)。外部数据仍需 Parser 校验，类型注解本身不拒绝错误对象。

本轮没有新增通用 Parser、业务验收器或 Runtime。也不为了合并少量相似字段创建继承层次。

### 文件二：新建 tests/test_finish_action.py

修改已有测试时，保留下列完整导入块：标准库异常、第三方 pytest、项目行动类型分别一组。添加 AgentAction 时不能删除 FrozenInstanceError，也无需重复导入 FinishAction。

```python
from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.action import AgentAction, FinishAction


def test_preserves_submission_text():
    answer = "  建议依次运行编译、正确性与性能测试。\n目前没有实际执行结果。  "
    reason = "当前请求只要求验证步骤说明。"

    action: AgentAction = FinishAction(answer=answer, reason=reason)

    assert action.kind == "finish"
    assert action.answer == answer
    assert action.reason == reason


@pytest.mark.parametrize("name", ["answer", "reason"])
@pytest.mark.parametrize("value", [None, True])
def test_rejects_non_string_fields(name, value):
    inputs = {"answer": "建议先运行编译测试。", "reason": "交付验证步骤说明。"}
    inputs[name] = value

    with pytest.raises(TypeError, match=name):
        FinishAction(**inputs)


@pytest.mark.parametrize("name", ["answer", "reason"])
@pytest.mark.parametrize("value", ["", " \n\t "])
def test_rejects_blank_fields(name, value):
    inputs = {"answer": "建议先运行编译测试。", "reason": "交付验证步骤说明。"}
    inputs[name] = value

    with pytest.raises(ValueError, match=name):
        FinishAction(**inputs)


def test_submission_cannot_be_rewritten():
    action = FinishAction(answer="当前没有 GPU 实测结果。", reason="说明验证边界。")

    with pytest.raises(FrozenInstanceError):
        action.answer = "所有测试都通过了"
```

4 个测试函数展开为 10 个用例：原文保留 1、错误类型 4、空白字段 4、字段保护 1。
测试同时导入 AgentAction，使公共导入入口成为测试收集的前提；如果别名被放到类内，pytest 会在收集阶段报 ImportError。变量注解展示联合类型的用法，不会在运行时检查联合成员，也不替代后续 Parser。
这些文本是手写测试样例，不表示项目已生成算子产物或执行过 GPU 测试。测试验证结果提议的形式，不评判答案质量；实际完成规则到 Runtime / Report Verifier 单元再测试。

## Run

在项目根保存文件后执行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

参考实现的测试目标是 115 passed：已有 105 个，加上本轮 10 个。还需模块导入、代码 Review 和 lint/format 通过；真实验收以 docs/status.md 为准。

## Observe

运行 `uv run --locked python`，逐行输入：

```python
from kernellens.domain.action import AgentAction, FinishAction
from kernellens.domain.state import TaskState, TaskStatus
from kernellens.domain.task import TaskRequest, TaskType
state = TaskState(TaskRequest(TaskType.DIAGNOSE, "说明 GEMM 的服务器验证步骤"))
state = state.transition_to(TaskStatus.RUNNING)
proposal: AgentAction = FinishAction(
    answer="建议先编译，再进行正确性与性能测试；当前没有实测结果。",
    reason="当前请求只要求验证步骤说明。",
)
print(proposal.kind)
print(state.status.value)
print(state.verification.compilation.value)
```

预期依次为 finish、running、not_run。
AgentAction 注解允许这里使用 FinishAction；构造提议不会把已有 state 自动改成 completed，也不会修改 compilation。
这只是独立领域对象的观察，不能据此声称完成条件已由 Runtime 实施。用 exit() 退出 Python。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 原文保留测试失败 | answer 的换行或空格不同 | 将 strip 的返回值保存回字段 | strip 只用于判断是否空白 |
| 字段保护测试报 NameError | 错误指向 pytest.raises(FrozenInstanceError)，尚未执行重新赋值 | 测试缺少异常类导入 | 恢复 from dataclasses import FrozenInstanceError，并合并重复项目导入；先修复测试本身再判断被测行为 |
| reason 非空但空答案也被接受 | answer 用例 DID NOT RAISE | 只校验了提交理由 | 检查循环同时包含 answer 和 reason |
| 模块存在，但无法导入 AgentAction | ImportError: cannot import name；模块没有该属性，FinishAction 类却有 | 别名缩进在类内 | 将别名移到模块顶层，并在测试中导入 AgentAction；formatter 不会替你改变作用域 |
| 类型别名语法报错 | SyntaxError 指向 type AgentAction | 用了旧解释器 | 通过 uv run --locked python --version 核对项目解释器 |
| AgentAction(...) 不能调用 | TypeError | 把类型别名当作构造器 | 使用 FinishAction(...) 等具体类 |
| 编辑器能识别类型但错误输入仍可进入其他函数 | 函数仅有注解 | 把静态声明当运行时检查 | 外部输入仍通过 Parser，不能只靠联合类型 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位，核心修复由用户完成。
回归方法：在实现仍有作用域错误时，补上测试中的 AgentAction 导入会让测试收集失败；修复后，同一测试应能收集并通过。若作用域已经修复，直接补齐测试覆盖，无需重新引入错误。测试通过只覆盖已验证的契约，不能代替公共入口检查。

## Checkpoint

本单元学习：提交提议、业务完成和实际验证的区别，保留结果原文，以及用联合类型表达有限行动集合。
用户实现已通过 Review：115 个测试及 lint/format 通过，公共导入和运行观察通过；已提交为 `42f0216 feat: add finish action and agent action union`，包含结果行动、联合类型、测试、讲义、专项图与相关文档。当前进度见 [当前能力与验证范围](status.md)。
本轮停在 RUN-002C；通用解析、业务验收器、状态转换消费与 Runtime 留到后续单元。
