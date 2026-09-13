# Python 环境与包安装

> 历史设计与学习讲义：文中的阶段进度、测试数量和旧提交号不代表当前版本。当前能力见 [状态说明](status.md)，参与开发见 [贡献指南](../CONTRIBUTING.md)。

## Context

当前处于 Phase 1。FND-003 的原生环境和 FND-004A 的包安装均已验收提交。本页解释环境与包安装；当前 FND-004B 的实现练习见 [configuration.md](configuration.md)。

2026-09-08 实测：Mac arm64；Homebrew uv 0.11.23（aarch64-apple-darwin）；项目 CPython 3.12.13（arm64）。解释器已在本机由 uv 管理，本轮直接复用，未下载或升级全局工具。

## Concept

| 概念 | 职责 | 本项目中的位置 |
| --- | --- | --- |
| Python 解释器 | 执行 Python 代码和标准库 | uv 管理的原生 CPython 3.12.13 |
| 版本选择 | 指定项目默认使用的解释器版本 | `.python-version` |
| 项目声明 | 声明名称、Python 范围与直接依赖 | `pyproject.toml` |
| 虚拟环境 | 隔离项目安装的依赖 | `.venv/`，不提交 Git |
| 锁文件 | 保存 uv 解析出的依赖版本与来源 | `uv.lock`，应提交 Git |

虚拟环境可以共享基础解释器和标准库，第三方包安装位置则独立。它不是容器，也不是执行不可信代码的安全沙箱。
`pyproject.toml` 声明需求，`uv.lock` 记录解析结果，`uv sync` 让环境与声明及锁文件一致。见 [uv 项目指南](https://docs.astral.sh/uv/guides/projects/)。

## Design

- 输入：已有的原生 uv、CPython 3.12.13 和项目声明。
- 输出：项目 `.venv`、uv 生成的锁文件，以及版本、架构、路径和隔离检查结果。
- 控制流：读取版本与项目声明 → 解析依赖 → 创建或同步环境 → 运行观察命令。
- `.python-version` 固定开发版本为 `3.12.13`；`requires-python = ">=3.12,<3.13"` 暂只声明 3.12 系列，尚未验证更高版本。
- 采用设计阶段的 3.12 基线，并复用本机已有解释器。3.12 处于安全维护期，官方列出的生命周期截至 2028-10；后续仍需跟进安全补丁和依赖兼容性。[Python 版本状态](https://devguide.python.org/versions/)
- `venv + pip` 也可以隔离依赖；当前使用 uv 统一版本选择、锁定和同步操作，减少手工维护步骤。

## Implementation

FND-003 中，助手创建 `.python-version` 和最小 `pyproject.toml`，由 uv 生成 `uv.lock` 与 `.venv`。

`dependencies = []` 表示当前没有第三方运行依赖。FND-003 使用过 `package = false`，只管理环境；FND-004A 已移除此项并增加构建后端，将项目本身安装到 `.venv`。
现在锁文件中的 `editable = "."` 表示本项目的可编辑安装。pytest 与 Ruff 已加入 dev 依赖组；配置与测试练习的进度见 docs/status.md，Agent 功能和模型调用尚未实现。

## Run

在本项目根目录执行。已有锁文件的环境同步使用：

```bash
uv sync --locked
```

`--locked` 要求锁文件与项目声明匹配，若不匹配则报错，避免这次安装悄悄重新解析依赖。`uv.lock` 由 uv 维护，不手工改写。
其他机器必须先有 uv；uv 可按 `.python-version` 获取匹配解释器，离线机器需要预先准备解释器和所需依赖。[uv Python 管理](https://docs.astral.sh/uv/concepts/python-versions/)

亲自执行以下观察命令：

```bash
uv run --locked python -c "import platform, sys; print(platform.python_version(), platform.machine()); print(sys.executable); print(sys.prefix != sys.base_prefix)"
```

Mac 上预期：

```text
3.12.13 arm64
<本项目路径>/.venv/bin/python3
True
```

末尾的可执行文件名也可能是 `python`；重点是版本、架构、项目 `.venv` 路径和隔离状态。

## Observe

- `platform.python_version()`：实际运行版本，不是根据配置文件推测的版本。
- `platform.machine()`：当前 Python 进程的架构，Mac 上本轮应为 `arm64`。
- `sys.executable`：这次启动了哪个解释器。
- `sys.prefix != sys.base_prefix`：当前是否运行在虚拟环境中。

`uv run` 会使用项目环境，无需先激活 `.venv`。单独输入 `python3` 由终端 PATH 决定，本机默认仍可能是 Homebrew 3.14.6。
在 VS Code 直接运行 Python 文件时，选择本项目 `.venv/bin/python` 作为解释器；仅有 `.python-version` 不等于编辑器已经切换解释器。

## Debug

| Problem | Evidence | Hypothesis | Verification | Fix |
| --- | --- | --- | --- | --- |
| 看到 3.14 或 Conda 路径 | 版本和 `sys.executable` 不符 | 使用了终端默认 Python 或编辑器旧配置 | 用上面的 `uv run` 命令对照 | 从项目根运行；编辑器选择项目 `.venv` |
| 看到 x86_64 | `platform.machine()` 不符 | 使用了 Intel 解释器或翻译模式终端 | 检查 `uname -m` 和 `uv python list --only-installed` | 选择原生终端和 ARM64 解释器，再针对证据修复环境 |
| 锁文件不匹配 | `--locked` 报错 | 声明变更后没有同步锁文件 | 对照 `git diff` 中的声明和锁文件 | 确认变更有意后执行 `uv lock`，再审阅锁文件与同步 |
| 无法找到解释器 | uv 提示版本不可用 | 本机未安装所选版本 | 查看 `uv python list --only-installed` | 联网安装选定版本，或准备离线解释器，不随意改成全局版本 |

遇到异常先保留输出，根据证据定位；不要直接删除环境或升级全部依赖。

## Checkpoint

- 环境基线已验证：3.12.13、arm64、项目虚拟环境、零第三方运行依赖；标准库 SSL、SQLite、asyncio 和 TOML 可用。
- 已验证：在项目内的临时副本中，使用现有解释器和未修改的锁文件创建全新环境；临时副本检查后清理。
- 本轮同步和验证附加了 `--offline --no-cache --no-python-downloads`，未进行网络下载，缓存仅使用临时目录。
- 复现范围：当前无第三方依赖的环境；没有验证未来依赖的 wheel、其他操作系统或 GPU 执行能力。
- FND-003 已完成用户观察和 Git Checkpoint，提交 `f316e25`；`.venv` 保持忽略。

## FND-004A：可安装、可导入的包

### Context 与 Concept

后续配置、工具和 Agent 代码需要通过稳定的导入路径组合。把源码正式安装到项目环境，可以减少依赖当前工作目录和手工修改 `sys.path` 的问题。

| 名称 | 本项目值 | 用途 |
| --- | --- | --- |
| 安装名称 | kernellens-agent | 项目元数据和安装记录中的名称 |
| 导入名称 | kernellens | Python 中使用 `import kernellens` |
| 源码位置 | src/kernellens/ | 存放后续可导入模块 |
| 包初始化文件 | src/kernellens/__init__.py | 标识普通 Python 包；当前只有说明文字 |

`src` 布局将可导入源码与仓库文档、脚本分开，有助于发现安装配置遗漏。[PyPA 布局说明](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

### Design 与 Implementation

输入是 `pyproject.toml` 和 `src/kernellens/__init__.py`；构建后端负责生成可安装的包，uv 将包安装进 `.venv`，Python 再按包名导入。

本轮新增的构建配置如下；安装名称与导入名称不同，因此显式指定 `module-name`：

```toml
[build-system]
requires = ["uv_build==0.11.23"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "kernellens"
```

选择 uv_build 是因为当前只有纯 Python 源码，现有 uv 可以直接完成构建。Hatchling 或 setuptools 也能完成这项工作；目前没有额外构建定制需求。
uv 在版本匹配时使用内置后端；本轮精确固定 0.11.23 并实际验证。将来若构建本地扩展，需要重新评估后端。[uv 构建后端](https://docs.astral.sh/uv/concepts/build-backend/)

构建依赖固定在 `[build-system].requires`，应用依赖解析结果由 `uv.lock` 保存，两者职责不同。
这些配置与只含说明文字的 `__init__.py` 由助手直接处理，尚未加入 Agent 核心逻辑。

### Run 与 Observe

在本项目根目录运行：

```bash
uv sync --locked
uv run --locked python -c "import kernellens; from importlib.metadata import version; print(version('kernellens-agent')); print(kernellens.__file__)"
```

预期：

```text
0.1.0
<本项目路径>/src/kernellens/__init__.py
```

安装记录在 `.venv`，导入文件却位于 `src`，这是可编辑安装的行为。修改已有源码后，新启动的 Python 进程能读取变化；已经运行的进程可能缓存导入的模块。
更改依赖或构建配置后仍需同步环境。`import` 只负责导入包，不会因此启动 Agent；当前没有 CLI 或 `__main__.py`。

### Debug

如果出现 `ModuleNotFoundError`，先观察 `sys.executable` 和所在目录，再核对 `uv sync --locked` 是否成功、`module-name` 是否匹配源码目录。
如果导入到了其他项目，检查 `kernellens.__file__` 与当前解释器；不要先用 `sys.path.append` 掩盖安装问题。

### Checkpoint

- 可编辑安装与版本读取通过；在项目目录之外，用隔离模式忽略当前目录和 PYTHONPATH 后仍能导入。
- wheel 构建、包内容检查及临时干净环境中的普通安装与导入通过；临时产物检查后清理。
- 本轮仅使用原生工具离线完成，无第三方运行依赖下载；没有执行应用测试套件或 GPU 检查。
- FND-004A 已由用户完成导入观察并提交：`6081c00 chore: add installable kernellens package`。
- FND-004B 的配置与测试已由用户实现并通过检查，当前 Git Checkpoint 见 docs/status.md。
