# FND-004B：集中配置与第一个自动化测试

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

FND-004A 已提交为 `6081c00`，项目包可正常导入。本单元为后续应用启动建立配置读取边界，并练习输入校验和可重复的测试。

pytest 9.1.1、Ruff 0.16.6 与检查配置已就绪。下面是用户亲手实现的参考代码；实际文件位置、完成情况与验证结果以 [当前能力与验证范围](status.md) 为准。

## Concept

配置把外部输入转成程序可以使用的值。本轮只有日志级别：缺省值、格式归一化、非法值拒绝。
单字段用标准库即可表达规则；更复杂的模型 Schema 在对应单元再引入 Pydantic。

pytest 自动发现 `test_` 函数，用断言描述期望行为，失败时报告差异。Ruff 检查常见代码问题、导入顺序和格式；它不能证明业务逻辑正确。
普通 assert 脚本和手工检查也能起步，当前选择 pytest 和 Ruff 是为了让后续用例与检查有统一入口。两者属于开发依赖，不放入应用运行依赖。
Ruff 配置显式声明 `kernellens` 是本项目包，使待实现模块的导入也能按项目代码分组。

## Design

| 项目 | 契约 |
| --- | --- |
| 配置项 | KERNELLENS_LOG_LEVEL |
| 输入接口 | `load_settings(environ: Mapping[str, str] \| None = None)` |
| `None` | 每次调用时读取进程环境 |
| 显式 Mapping | 仅读取传入映射，包括空字典；不回退到进程环境 |
| 缺少配置项 | INFO |
| 归一化 | 去除首尾空格，转为大写 |
| 有效值 | DEBUG、INFO、WARNING、ERROR、CRITICAL |
| 无效字符串，包括空字符串 | 抛出 ValueError，并标明配置项名称 |
| 输出 | `Settings(log_level=...)`；本轮只保存配置，不初始化日志系统 |

控制流：选择输入来源 → 读取默认值 → 归一化 → 校验 → 返回配置或报错。
这次传入映射的能力是最小的依赖注入：测试可以控制输入，不依赖运行测试的终端恰好设置了什么。
这里的输入是进程环境或调用者提供的映射，不包含自动加载 `.env` 文件。

## Implementation：由用户亲手输入

在 `src/kernellens/config.py` 创建：

```python
import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    log_level: str


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    log_level = env.get("KERNELLENS_LOG_LEVEL", "INFO").strip().upper()
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    if log_level not in allowed:
        raise ValueError(
            "KERNELLENS_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
        )

    return Settings(log_level=log_level)
```

- `dataclass` 自动生成构造方法和便于观察的表示；`frozen=True` 阻止常规属性重新赋值。类型标注与 frozen 本身不校验值，本轮有效性检查由加载函数负责。
- `Mapping[str, str]` 表达只需读取键值的接口；`None` 表示调用者没有传入替代环境。
- `environ is None` 保留空字典的含义。若写成 `environ or os.environ`，空字典会被错误地替换成真实环境。
- 函数只在调用时读取环境；导入模块时不创建全局配置快照。
- 无效值直接报错，让调用者知道配置未被接受；不静默替换成 INFO。

在 `tests/test_config.py` 创建：

```python
import pytest

from kernellens.config import load_settings


def test_explicit_empty_environment_uses_default(monkeypatch):
    monkeypatch.setenv("KERNELLENS_LOG_LEVEL", "ERROR")

    assert load_settings({}).log_level == "INFO"


def test_loads_and_normalizes_process_environment(monkeypatch):
    monkeypatch.setenv("KERNELLENS_LOG_LEVEL", " debug ")

    assert load_settings().log_level == "DEBUG"


@pytest.mark.parametrize("value", ["", "verbose"])
def test_rejects_invalid_log_level(value):
    with pytest.raises(ValueError, match="KERNELLENS_LOG_LEVEL"):
        load_settings({"KERNELLENS_LOG_LEVEL": value})
```

第一个测试刻意让进程环境与显式空输入冲突，验证输入隔离；第二个验证真实读取入口和归一化；第三个分别验证空值与不支持的级别。
`monkeypatch` 由 pytest 根据参数名提供，测试结束后自动撤销环境修改；`pytest.raises` 声明预期异常。[环境隔离](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)、[异常断言](https://docs.pytest.org/en/stable/how-to/assert.html)。

## Run

完成两个文件后，在本项目根目录运行：

```bash
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

pytest 预期为 `4 passed`：三个测试函数，其中参数化函数运行两次。实际验收记录见 [当前能力与验证范围](status.md)。
Ruff 预期没有代码问题；格式不符时，可运行 `uv run --locked ruff format src tests` 处理机械排版，再重新检查。

## Observe

```bash
uv run --locked python -c "from kernellens.config import load_settings; print(load_settings({}))"
```

预期 `Settings(log_level='INFO')`。显式空字典让这个观察不受终端环境影响。
配置检查和测试通过后仍需代码 Review，再保存完整学习单元的 Git 提交。

## Debug

| Problem | Evidence | Hypothesis | Verification / Fix |
| --- | --- | --- | --- |
| 收集失败 | ModuleNotFoundError | 文件路径或解释器不对 | 核对两个文件的位置、拼写和 uv run 使用的项目 |
| 空输入得到 ERROR | 第一个断言显示 ERROR 而非 INFO | 用真值判断选择了环境 | 检查是否误写 `environ or os.environ`，改成显式 None 判断 |
| 未报错 | DID NOT RAISE | 缺少校验，或将空值当默认值 | 对照输入契约，检查默认值与有效值校验顺序 |
| 格式检查失败 | Ruff 指出文件需格式化 | 机械排版差异 | 使用 formatter 后阅读差异，再运行检查 |

顺序保持 Problem → Evidence → Hypothesis → Verification → Fix。先保留报错，用户修改后再复查。

## Checkpoint

完成本单元需要实现、运行观察、代码 Review 和实际检查；参考代码的语法检查不等于应用测试通过。
本轮预计学会配置读取边界、依赖注入、dataclass、异常断言和环境隔离。完成后回复“已完成”或“帮我检查”，先 Review 当前两个文件，不进入下一阶段。
Review 与检查通过后建议提交 `feat: add validated application settings`，包含配置、测试、开发工具与相关文档；提交前核对暂存范围。
