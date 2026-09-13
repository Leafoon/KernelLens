# KernelLens

**面向 TileLang 算子开发与优化的终端 Agent。** 从需求生成候选、基于 baseline 提出优化、读取代码与日志进行诊断，并保留来源证据和验证记录。当前 MVP 聚焦基础 GEMM。

KernelLens 与 TileLang 知识包在同一仓库分发。普通用户无需克隆 TileLang，也无需 GPU 即可运行 Agent 和离线检索；候选的编译、数值正确性与性能仍需在目标 GPU 上验证。

## 功能

| 能力 | 行为 |
| --- | --- |
| 生成 | 根据 shape、dtype 和目标 GPU 保存算子候选并进行静态检查 |
| 优化 | 读取 baseline，保留计算契约，另存候选并说明实验假设 |
| 诊断 | 阅读工作区代码、日志或用户报告，返回带证据的解释 |
| RAG | 内置 4,337 个语义单元，分 API、Concept、Example、Compiler、Operator 检索 |
| GPU 输入 | 支持需求内声明、`--gpu`、`/gpu`；缺少型号时主动询问并恢复原任务 |
| 连续会话 | 工作区切换、历史记录、运行轨迹、中断后继续 |
| 验证与预算 | AST、有限 GEMM/API 检查、交付审核、调用预算和报告比较 |

单进程、单 Agent；云端模型兼容 Chat Completions，支持原生工具调用和 JSON 行动模式。无需向量数据库或 embedding 服务。

## 快速开始

需要 **Python 3.12** 和 **uv**。当前本地验收平台为 macOS ARM64；其他平台尚未完成同等验收。

```bash
git clone https://github.com/Leafoon/KernelLens.git
cd KernelLens
uv sync --locked
cp .env.example .env
```

仓库目前为私有，克隆需要访问权限。在 `.env` 中填写自己的配置：

```dotenv
base_url=https://your-provider.example/v1
model=your-model-id
api_key=your-private-key
```

启动 Agent，选择一个已存在的任务工作区：

```bash
uv run --locked kernellens
```

```text
workspace> /path/to/my-workspace
你> /gpu NVIDIA A100
你> /generate 生成基础 GEMM，M=N=K=128，A/B/C float16，累加 float32。
你> /optimize 基于 artifacts/gemm.py 提出一个参数优化，保存候选和实验说明。
你> /diagnose 读取 compile.log，分析错误并引用证据。
你> /exit
```

生成、优化缺少目标 GPU 型号时，会先询问并进入 `waiting_input`，该次输入检查不调用模型。直接回复型号即可继续；`/gpu` 查看，`/gpu clear` 清空。不会自动把开发机或示例中的设备当作执行目标。

## 常用命令

```bash
# 指定工作区和目标 GPU
uv run --locked kernellens -w /path/to/workspace --gpu "NVIDIA A100"

# 单次任务：结果输出 JSON，进度输出到 stderr
uv run --locked kernellens -w /path/to/workspace -p '解释 README.md' --json

# 恢复原会话，包括等待中的补充信息
uv run --locked kernellens -w /path/to/workspace --resume SESSION_ID

# 仅校验和查询知识库：不需要模型 Key、GPU 或 TileLang 克隆
uv run --locked python -m kernellens.knowledge validate
uv run --locked python -m kernellens.knowledge search 'T.copy 的同步语义'

# 开发检查：不调用真实供应商
uv run --locked python scripts/check_project.py
```

模型配置在启动时加载，修改后需重启。环境变量优先于 dotenv，CLI 参数优先于环境变量。真实 Agent 任务使用配置的模型服务，可能产生费用；离线知识查询和默认开发检查不调用供应商。

## 仓库内容

```text
src/kernellens/             CLI、Agent Loop、模型适配、工具、审核与 GPU 输入
src/kernellens/data/tilelang/
                           内置知识正文与索引、manifest、上游许可和 notices
tests/                     自动测试与本地模型替身
knowledge/                 公开的检索回归问题
examples/                  服务器验证报告模板
scripts/                   开发检查、知识评估、图源同步及显式真实验收
docs/                      使用手册、原理、架构决策和学习材料
```

知识包约 31 MiB，完整正文保存在 SQLite 中，并随 wheel 分发。维护者更新知识时才需要原始 TileLang 源码，流程见 [RAG 文档](docs/tilelang-rag.md)。

仓库不包含 `.env`、个人 Agent 会话、生成的实验产物、本地 TileLang 克隆、虚拟环境、缓存或构建包。具体规则见 [.gitignore](.gitignore) 和 [发布内容说明](docs/repository.md)。

## 验证边界

当前本地回归为 **438 项测试通过、28/28 条检索回归通过**，知识包校验与 sdist/wheel 构建通过。详见 [当前状态](docs/status.md) 和 [工程验证](docs/validation.md)。

检索到源码、工具调用完成、静态检查通过和 GPU 运行正确是不同结论。程序不自动运行候选；没有可比较的真实测量时不宣称性能提升。模型产物及其运行建议需要独立审阅。

## 文档与贡献

- [CLI 使用手册](docs/cli.md)
- [Agent 功能、架构与方法原理](docs/agent-guide.md)
- [TileLang RAG 原理与知识包维护](docs/tilelang-rag.md)
- [架构决策](docs/decisions/002-cli-agent.md)与[独立图源](docs/diagrams/README.md)
- [贡献指南](CONTRIBUTING.md)与[安全说明](SECURITY.md)

自有代码的许可证暂未确定。内置上游资料的许可单独保留，见 [第三方声明](NOTICE.md)；上游许可不代表 KernelLens 自有代码已采用同一许可证。
