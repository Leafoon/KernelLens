# ADR 001：工具输入采用 Pydantic 声明与 JSON Schema 导出

Status: Accepted。工具参数模型、注册与校验现已实现；本文保留最初选型背景。
Date: 2026-09-10。

## Context

最初的有限 Runtime 中，CallToolAction 只校验通用标量映射。
Phase 3 需要逐个工具的参数规则，并向后续模型适配器提供参数说明。
如果分别维护 Python 校验代码和 Schema 字典，规则变更容易只更新其中一份。

## Decision

从 read_report 的 ReadReportArguments 开始，工具输入使用 Pydantic 2.13.5：
通过 model_validate 校验输入，通过 model_json_schema 导出声明规则。
Pydantic 支持由模型生成可 JSON 序列化的 Schema 字典。[官方说明](https://docs.pydantic.dev/latest/concepts/json_schema/)

参数模型采用 strict=True、extra="forbid"、frozen=True；
path 先限定为包含非空白字符的字符串，保留原文，不执行路径解析或文件读取。
既有领域 dataclass、Parser 和 Runtime 保持原样；本单元不建立 Registry 或 Provider。

## Alternatives

| 方案 | 优点 | 当前取舍 |
| --- | --- | --- |
| 标准库校验加手写 Schema | 无新依赖，简单单字段足够 | 需要同步两份规则，后续多个工具易重复 |
| JSON Schema 字典加独立验证库 | Schema 为唯一规则来源 | 仍需单独组织 Python 数据对象；本项目以 Python 参数模型为接口 |
| Pydantic 参数模型 | 字段定义同时支持校验与 Schema 导出 | 增加运行依赖与原生组件，需锁定版本并验证架构 |

## Reason

1. 解决什么问题：工具特定的输入边界及模型可读规则需要保持一致。
2. 为什么现在：Phase 3 正式开始工具 Schema；不再只有通用 CallToolAction。
3. 如果不用：可以继续手写，但必须承担校验与 Schema 同步、错误组织和重复代码。
4. 更简单方案：仅检查一个 path 时用 if 足够；引入依赖的原因是本阶段的双重输出要求，而非这个字段复杂。
5. 选择原因：让用户集中实现工具业务契约；Agent 控制逻辑已经亲手实现，不交给参数库管理。

## Consequences

- 新增运行依赖 pydantic==2.13.5；传递依赖由 uv.lock 固定。
- 只依赖本例声明式约束导出 Schema；不能假定任意 Python 自定义校验都会自动变成 JSON Schema。
- Schema 只描述输入，不替代执行权限、路径限制、超时或真实结果审核；Provider 支持的 Schema 子集在接入时核对。
- frozen 约束常规赋值，不是防篡改机制；外部参数通过 model_validate 进入，不使用跳过校验的构造方式。
- 暂不抽取所有工具共用的模型基类；出现实际重复后再讨论。

## Compatibility & Validation

选取核对时的正式版本 2.13.5，未使用 2.14 预发布版。[PyPI 版本记录](https://pypi.org/project/pydantic/2.13.5/)

本地实测：CPython 3.12.13 / arm64，pydantic-core 2.46.5 的安装标签为
cp312-cp312-macosx_11_0_arm64，扩展文件为 Mach-O arm64。
安装时指定 --no-build-package pydantic-core，只接受其已构建分发；未使用 Rosetta，也未本地编译该组件。
对应发行提供 macOS ARM64 wheel。[pydantic-core 发行文件](https://pypi.org/project/pydantic_core/2.46.5/)

依赖安装后原有 326 个测试通过（0.12s），Ruff lint/format 通过（33 个 Python 文件，包含空包入口）。
上述为最初依赖选型阶段的结果；当前能力和维护者验证记录见 [当前状态](../status.md)。Linux ARM64 服务器环境尚未完成同等验收。
