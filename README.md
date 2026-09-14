# KernelLens

**面向 TileLang 算子开发与优化的终端 Agent。** 从需求生成候选、基于 baseline 提出优化、读取代码与日志进行诊断，并保留来源证据和验证记录。

> **TypeScript 重写版** — 基于 Python 原版的 TypeScript/Node.js 移植，使用 Ink (React) 终端 UI。

## 功能

| 能力 | 行为 |
| --- | --- |
| 生成 | 根据 shape、dtype 和目标 GPU 保存算子候选并进行静态检查 |
| 优化 | 读取 baseline，保留计算契约，另存候选并说明实验假设 |
| 诊断 | 阅读工作区代码、日志或用户报告，返回带证据的解释 |
| RAG | 内置知识库，分 API、Concept、Example、Compiler、Operator 检索 |
| 终端界面 | Ink (React) 驱动的对话式 TUI，支持 `/` 命令和实时状态 |
| 验证与预算 | 工具证据追踪、交付审核、调用预算控制 |

## 技术栈

| 组件 | 选型 |
| --- | --- |
| 语言 | TypeScript 5.6+ (ESM) |
| 运行时 | Node.js 20+ |
| 包管理 | pnpm |
| 终端 UI | Ink 5 + React 18 |
| LLM 客户端 | OpenAI SDK |
| Schema 验证 | Zod |
| 数据库 | better-sqlite3 (WAL mode) |
| 构建 | tsup |
| 测试 | Vitest |
| Lint | Biome |

## 快速开始

需要 **Node.js 20+** 和 **pnpm**。

```bash
git clone https://github.com/Leafoon/KernelLens.git
cd KernelLens
pnpm install
cp .env.example .env
```

在 `.env` 中填写配置：

```dotenv
KERNELLENS_API_KEY=your-api-key
KERNELLENS_MODEL=gpt-4o
KERNELLENS_BASE_URL=https://api.openai.com/v1
```

启动终端界面：

```bash
pnpm dev
```

或构建后运行：

```bash
pnpm build
node dist/index.js run
```

## 命令行用法

```bash
# 交互式 TUI
pnpm dev

# 指定工作区和模型
pnpm dev -- --workspace /path/to/workspace --model gpt-4o

# 查看配置
pnpm dev -- config

# 环境检查
pnpm dev -- doctor
```

TUI 内置命令：

| 命令 | 说明 |
|------|------|
| `/generate <需求>` | 生成算子候选 |
| `/optimize <需求>` | 优化现有候选 |
| `/diagnose <需求>` | 诊断或解释代码 |
| `/help` | 显示帮助 |
| `/clear` | 清空对话 |
| `/status` | 显示配置 |

## 项目结构

```text
src/
├── agent/              Agent Loop (budget, handlers, step, loop)
├── config/             配置加载与验证 (Zod schema)
├── domain/             领域类型 (action, state, task, observation)
├── knowledge/          知识库 (FTS5, 术语扩展, 意图路由)
├── models/             LLM 适配层 (provider, client, adapter, context)
├── prompts/            系统提示词
├── review/             交付审核
├── security/           路径安全, 密钥脱敏
├── storage/            SQLite 存储
├── tools/              工具注册与执行 (workspace, definitions)
├── tui/                Ink 组件 (App, ChatPane, StatusLine)
├── application.ts      顶层协调器
├── cli.ts              CLI 入口 (commander)
├── constants.ts        全局常量
├── exceptions.ts       错误层次
└── index.ts            包入口
test/                   测试 (209 tests)
```

## 开发

```bash
# 类型检查
pnpm typecheck

# Lint
pnpm lint
pnpm lint:fix

# 测试
pnpm test
pnpm test:watch

# 构建
pnpm build

# 全部检查
pnpm ci
```

## 架构

### Agent Loop

```
User Input → Application.turn()
  → DecisionAdapter.decide() → LLM
  → AgentAction (call_tool | finish | request_input)
  → Handler (applyCallTool | applyFinish | applyRequestInput)
  → StepRecord → loop (or terminal state)
```

### 状态机

```
PENDING → RUNNING → COMPLETED / FAILED / BUDGET_EXHAUSTED / CANCELLED
                    → WAITING_INPUT → RUNNING / FAILED / CANCELLED
```

### 工具调用

```
ToolRegistry.execute(action)
  → Zod schema 验证参数
  → 执行工具函数
  → 分配 Evidence ID (E1, E2, ...)
  → 返回 ToolObservation
```

## 验证

- **209 项测试通过** (22 个测试文件)
- 类型检查 (tsc --noEmit) 通过
- Biome lint 通过
- 构建 (tsup) 通过

检索到源码、工具调用完成、静态检查通过和 GPU 运行正确是不同结论。程序不自动运行候选；没有可比较的真实测量时不宣称性能提升。

## 从 Python 版迁移

| Python 模块 | TypeScript 对应 |
|-------------|----------------|
| `domain/action.py` | `src/domain/action.ts` |
| `domain/state.py` | `src/domain/state.ts` |
| `runtime/loop.py` | `src/agent/loop.ts` |
| `runtime/handlers.py` | `src/agent/handlers.ts` |
| `models/client.py` | `src/models/client.ts` |
| `models/adapter.py` | `src/models/adapter.ts` |
| `tools/registry.py` | `src/tools/registry.ts` |
| `tools/workspace.py` | `src/tools/workspace.ts` |
| `review.py` | `src/review/reviewer.ts` |
| `tui.py` (Textual) | `src/tui/` (Ink) |
| `application.py` | `src/application.ts` |
| `prompts.py` | `src/prompts/system.ts` |

## 许可证

MIT License. 内置上游资料的许可单独保留，见 [NOTICE.md](NOTICE.md)。
