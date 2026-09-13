# TOOL-001A：工具参数契约与 JSON Schema

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前进入 Phase 3 — Models & Controlled Tools。
Phase 2 已提交为 `df1fee6 feat: implement bounded agent execution loop`，进入本单元前工作区干净。

已有 Runtime 能调用程序注入的执行器，但 CallToolAction 只要求 arguments 是通用标量映射。
例如 {"path": True} 可以成为合法的通用行动，却不适合读取报告工具。
本单元只定义后续 read_report 的参数契约；工具身份、注册与实际执行留给接下来的单元。

## Concept

### 同一声明，两种用途

参数契约一方面把外部数据变成受约束的 Python 对象，另一方面描述给模型应该填写什么字段。
Pydantic 的 model_validate 用于校验，model_json_schema 用于导出可 JSON 序列化的规则字典；
model_dump 导出的是某次已校验数据，和 Schema 有不同用途。[官方 JSON Schema 说明](https://docs.pydantic.dev/latest/concepts/json_schema/)

本例中的三层边界是：

| 层次 | 当前职责 | 本例 |
| --- | --- | --- |
| CallToolAction | 通用提议结构 | 工具名、参数标量映射、理由 |
| ReadReportArguments | 某个工具的参数规则 | 必须有 path，且为非空白字符串 |
| 后续执行器 | 是否可执行、如何执行 | 路径范围、文件读取和资源限制 |

参数通过校验不等于允许访问文件。这个类不会读取、创建或检查文件，也不会调用模型。

### 为什么现在引入 Pydantic

仅检查一个字符串，用已有 dataclass 加 if 就能完成。
现在还需要从同一份声明导出工具参数 Schema；手写两份规则容易在修改时失配。
因此采用 Pydantic，既有 Runtime 和领域对象保持原样。取舍的五个问题与替代方案见
[ADR 001](decisions/001-tool-input-schemas.md)。

Pydantic 默认可能进行类型转换，我们显式选择严格校验，让错误参数暴露出来；
严格规则会随类型和 Python / JSON 输入方式有所区别，本单元只约束字符串，不把 strict 理解成所有场景都完全相同。[Strict Mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)

## Design

输入是包含 path 的字典；成功输出 ReadReportArguments，失败抛 ValidationError。
Schema 导出不需要一次具体的参数输入，返回规则字典。

| 规则 | 设计原因 |
| --- | --- |
| path 必填，无默认值 | 缺失时不能猜测要读取哪个文件 |
| path 必须是 str | 不把数字、bool 或 bytes 悄悄转换成路径 |
| 至少一个字符，并匹配非空白字符 | 拒绝空字符串及只含空白的内容 |
| 保留路径原文 | 空格可能属于文件名，不在参数层 strip 或 resolve |
| 禁止额外字段 | 不静默忽略模型填写的未知参数 |
| 禁止常规字段赋值 | 已校验参数不因后续普通赋值漂移 |

extra="forbid" 会拒绝未知字段，frozen=True 限制常规属性修改；
它们是模型配置，不是文件访问授权。[ConfigDict](https://docs.pydantic.dev/latest/api/config/)

流程见 [参数校验与 Schema 图](diagrams/tool-arguments.md)。
本单元采用字段声明中的长度和 pattern 约束；通用 Schema 与实际 Provider 的支持子集要在接入阶段核对。
不把导出成功当作供应商已经接受，也不在此增加 Registry、执行函数或路径权限检查。

## Implementation

### 助手已处理的工程准备

- pyproject.toml 添加固定运行依赖 pydantic==2.13.5，uv.lock 锁定传递依赖；没有替换 Python 或现有开发工具。
- 创建空的 src/kernellens/tools/__init__.py，只建立当前需要的包入口。
- 新增本讲义、独立图和 ADR，同步项目状态。没有写入下面两个核心文件。

本地已确认 Python 3.12.13 / arm64，pydantic-core 2.46.5 的扩展为原生 Mach-O arm64，
安装标签为 cp312-cp312-macosx_11_0_arm64。未使用 Rosetta 或本地编译 pydantic-core。
具体依赖和复现命令见 [技术方向](technology.md#tool-001a-依赖验证)。

### 1. 创建参数模型

文件：`src/kernellens/tools/arguments.py`，由你亲手输入：

```python
from pydantic import BaseModel, ConfigDict, Field


class ReadReportArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    path: str = Field(
        min_length=1,
        pattern=r"\S",
        description="待读取报告的路径；访问范围由执行器校验。",
    )
```

按逻辑块理解：

- 继承 BaseModel，让字段声明参与运行时校验和 Schema 导出；单纯的 Python 类型标注本身不会做到这些。
- model_config 规定这个输入边界的严格性、未知字段处理和常规修改规则。
- path 没有默认值，所以调用者必须提供。
- Field 声明长度、正则与说明；r"\S" 中的 r 表示 Python 原始字符串，\S 表示非空白字符。
- pattern 在此检查字符串是否包含匹配，不要求整个字符串只有一个字符。正常文件名中的空格会保留。
- description 是用途说明，不负责执行权限校验。

冻结模型并不意味着所有构造路径都自动校验：本课程的外部字典通过 model_validate 进入，
不使用跳过校验的构造快捷方式。当前只有字符串字段，不涉及嵌套可变容器。

### 2. 创建参数契约测试

文件：`tests/test_tool_arguments.py`。6 个测试函数，参数化后预期 16 个用例：

```python
import pytest
from pydantic import ValidationError

from kernellens.domain.action import CallToolAction
from kernellens.tools.arguments import ReadReportArguments


@pytest.mark.parametrize(
    "path", ["reports/compile.json", "报告.json", " reports/my report.json "]
)
def test_validates_action_arguments_and_preserves_the_path(path):
    payload = {"path": path}
    action = CallToolAction("read_report", payload, "读取报告。")

    arguments = ReadReportArguments.model_validate(dict(action.arguments))

    payload["path"] = "changed.json"
    exported = arguments.model_dump()
    assert exported == {"path": path}
    exported["path"] = "another.json"
    assert arguments.path == path
    assert action.arguments["path"] == path


@pytest.mark.parametrize(
    ("payload", "location", "error_type"),
    [
        ({}, ("path",), "missing"),
        ({"path": None}, ("path",), "string_type"),
        ({"path": 123}, ("path",), "string_type"),
        ({"path": True}, ("path",), "string_type"),
        ({"path": b"report.json"}, ("path",), "string_type"),
        ({"path": ""}, ("path",), "string_too_short"),
        ({"path": " \t\n"}, ("path",), "string_pattern_mismatch"),
        ({"path": "report.json", "extra": 1}, ("extra",), "extra_forbidden"),
    ],
)
def test_rejects_arguments_outside_the_tool_contract(payload, location, error_type):
    with pytest.raises(ValidationError) as caught:
        ReadReportArguments.model_validate(payload)

    errors = caught.value.errors(include_input=False, include_url=False)
    assert len(errors) == 1
    assert errors[0]["loc"] == location
    assert errors[0]["type"] == error_type


def test_generic_action_acceptance_does_not_validate_tool_arguments():
    action = CallToolAction("read_report", {"path": True}, "读取报告。")

    with pytest.raises(ValidationError) as caught:
        ReadReportArguments.model_validate(dict(action.arguments))

    assert caught.value.errors(include_input=False)[0]["type"] == "string_type"


def test_schema_describes_the_same_declared_input_rules():
    schema = ReadReportArguments.model_json_schema()

    assert schema["type"] == "object"
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"path"}
    path_schema = schema["properties"]["path"]
    assert path_schema["type"] == "string"
    assert path_schema["minLength"] == 1
    assert path_schema["pattern"] == r"\S"
    assert path_schema["description"] == "待读取报告的路径；访问范围由执行器校验。"


def test_validated_arguments_reject_normal_assignment():
    arguments = ReadReportArguments.model_validate({"path": "report.json"})

    with pytest.raises(ValidationError) as caught:
        arguments.path = "changed.json"

    assert caught.value.errors(include_input=False)[0]["type"] == "frozen_instance"
    assert arguments.path == "report.json"


@pytest.mark.parametrize("path", ["../outside.json", "/private/report.json"])
def test_shape_validation_does_not_authorize_file_access(path):
    arguments = ReadReportArguments.model_validate({"path": path})

    assert arguments.path == path
```

这些用例验证本项目选定的边界，不对依赖库的所有功能重新测试：

| 用例组 | 数量 | 学习目标 |
| --- | ---: | --- |
| 合法路径与原文保留 | 3 | 从行动参数进入工具契约，外部字典及导出字典不会改写已校验值 |
| 非法参数 | 8 | 缺失、类型、空文本和未知字段的可定位错误 |
| 通用结构与工具契约 | 1 | CallToolAction 接受 bool，不代表 read_report 接受 bool 路径 |
| Schema 导出 | 1 | 必填、类型、未知字段、长度和 pattern 对应声明 |
| 冻结赋值 | 1 | Pydantic 的赋值错误是 ValidationError，与 dataclass 的异常类型不同 |
| 路径授权边界 | 2 | 结构校验可以接受相对上级路径和绝对路径，执行器后续必须另行判断 |

最后两个路径只是字符串测试材料，不会访问文件。
测试检查错误的 loc 和 type，避免依赖完整英文错误文案；输出错误时只选必要字段。
后续公共日志的错误脱敏与错误分类单独设计，不因此示例就认为已经完成。

## Run

在项目根目录执行：

```bash
uv sync --locked
uv run --locked pytest -q tests/test_tool_arguments.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest -q
```

依赖已由助手同步；uv sync --locked 是你复现当前环境的入口。
预期新增 **16 passed**，完整回归目标 **342 passed = 326 + 16**，目前尚未实测。

本轮实际完成的是依赖安装后的原有回归：326 passed（0.12s），Ruff lint/format 通过（33 个 Python 文件）。
参考实现与测试只做 AST、Ruff 校验；核心参数模型及新测试待你输入，不能把基线通过当作新功能已验收。

## Observe

输入完成后执行：

```bash
uv run --locked python - <<'PY'
import json

from pydantic import ValidationError

from kernellens.domain.action import CallToolAction
from kernellens.tools.arguments import ReadReportArguments


schema = ReadReportArguments.model_json_schema()
print(json.dumps(schema, ensure_ascii=False, indent=2))

arguments = ReadReportArguments.model_validate({"path": "reports/compile.json"})
print("data:", arguments.model_dump())

action = CallToolAction("read_report", {"path": True}, "读取报告。")
print("action:", action.kind)
try:
    ReadReportArguments.model_validate(dict(action.arguments))
except ValidationError as error:
    for item in error.errors(include_input=False, include_url=False):
        print(f"{item['loc'][0]}: {item['type']}")
PY
```

Schema 中应该看到：

- type 为 object；
- required 包含 path；
- additionalProperties 为 false；
- path 的 type 为 string、minLength 为 1，并包含 pattern 和用途说明。

末尾预期：

```text
data: {'path': 'reports/compile.json'}
action: call_tool
path: string_type
```

先看“规则”和“本次数据”的区别，再看通用行动已成功构造、工具参数仍被拒绝的边界。
整个例子没有执行工具、读取报告或请求云端模型。当前示例尚未运行，待你输入后验收。

## Debug

| Problem | Evidence | Hypothesis | Verification → Fix |
| --- | --- | --- | --- |
| 无法导入 pydantic | ModuleNotFoundError | 用错解释器或未同步锁定依赖 | 在项目根同步环境，再通过 uv run 运行 |
| 无法导入工具参数类 | kernellens.tools.arguments 导入错误 | 文件还没创建或路径不对 | 核对 src/kernellens/tools/arguments.py 和类名 |
| 额外字段被接受 | extra_forbidden 测试失败 | 未配置 extra="forbid" | 对照 model_config；不在测试中删掉未知字段掩盖问题 |
| 空白字符串被接受 | pattern 用例失败 | 只有长度检查，或误写了正则 | 区分空字符串与空白字符串，核对 r"\S" |
| 路径内容被修改 | 原文保留测试失败 | 使用 strip / 自动路径解析 | 参数层返回原字符串，路径解析放执行器 |
| Schema 看起来像一条路径数据 | 没有 properties / required | 混用 model_dump 与 model_json_schema | 对照两种方法的调用对象和返回用途 |

按 Problem → Evidence → Hypothesis → Verification → Fix 定位；核心修复由你完成。
遇到新错误先保留字段位置与错误类型，不立即添加宽松转换或默认值。

## Checkpoint

本步目标：理解工具专属输入边界、严格校验、Schema 与数据的区别，
以及“结构有效”和“允许执行”为什么必须分开判断。

工程准备已完成；参数模型和 16 个新用例待你亲手输入。
完成输入、运行和观察后回复“已完成”，我再读取实际代码 Review；现在先不提交。

验收后建议 `feat: add report tool argument schema`，包含参数模型、测试、包入口、
依赖及配套文档。随后再建立工具定义与注册机制，不提前实现实际文件读取。
