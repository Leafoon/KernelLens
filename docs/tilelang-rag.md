# TileLang 结构化 RAG：知识、检索与 Agent 工作方式

KernelLens 现在能够先检索一份专门整理的 TileLang 知识库，再把少量相关材料交给模型。模型可以按知识编号继续阅读，生成候选后还会检查部分公开 API 契约。

知识由维护者从 TileLang 源码与文档抽取，当前来源为 VERSION `0.1.14`、commit `0e5c293c70944f346ac1462e6f460c827e82600a`。普通用户直接使用随项目提供的 `src/kernellens/data/tilelang/`，无需克隆 TileLang；来源信息见包内 manifest。这里保留出处，不实现版本选择或更新服务。

详细设计见 [实施计划](decisions/003-tilelang-rag.md)，流程图的唯一图源见 [RAG 流程图](diagrams/tilelang-rag.md)。

## 1. 用户输入要求后，发生什么

假设输入：

> 生成一个 M=N=K=128、输入输出 float16、累加 float32 的 GEMM。

1. CLI 接收要求，先检查目标 GPU。若需求、当前会话及默认配置都未提供型号，进入 `waiting_input` 并询问，不调用模型或执行预检索。用户回复如“NVIDIA A100”后继续原目标，创建新的运行，提取明确的 GEMM 约束。
2. CLI 默认加载随包知识库，将原始目标交给问题路由器。这里命中“算子生成”，选择 Operator、Example、API 和 Concept 索引。
3. 各索引最多取 100 个候选，在程序里按已知目标后端过滤、合并、去重和排序。普通 GEMM 任务会优先参考基础 GEMM；attention 性能章节不会因为提到 GEMM 就挤进结果。GPU 型号也进入检索问题和模型上下文；后端过滤不证明特定架构/指令兼容，未知标签的通用知识仍可返回。
4. 自动预检索最多取 3 个单元，控制在 7000 字符以内。预算允许时携带短单元的完整源码并标为 `source_complete=true`，优先为完整示例与相关 API 分配预算，其他单元提供摘要、签名、来源和 K 编号。整个仓库不会进入模型上下文。
5. 这份结果在第一次模型请求前加入当前任务材料。程序把这次检索保存为 `decision: 0`，与模型作出的第 1 次决策区分。
6. 预检索已经提供的完整源码不必重复读取；其他相关 kernel 构造函数及 API 用 `read_knowledge` 阅读。源码太长时按 `next_line` 继续，缺失信息用 `search_knowledge` 补查。
7. 模型适配示例，使用文件工具保存候选；`check_python` 检查 Python 语法、可识别的 GEMM 声明，以及知识库可确认的公开导出、关键字参数和局部 GEMM 累加器初始化。
8. 交付审核检查候选版本、静态结果、baseline（优化任务）、参考材料完整阅读情况和本轮 E 证据引用。拒绝原因回到模型，允许在剩余预算内修正。
9. 最终回答、引用、工具步骤和生成文件记录保存在工作区的 `.kernellens/` 中。

模型仍负责分析和写代码；检索器负责选择材料，程序负责执行工具和可确定的检查。检索器不修改模型权重，也不执行 TileLang 源码。

## 2. 为什么需要专用知识结构

TileLang 同时包含用户写 kernel 的 DSL、Python API、编译器变换和多种后端。把所有文件混到一个检索入口，会让“怎么用 `T.copy`”和“CopyNode 如何 lowering”互相干扰。

这个版本还有方言差异：`tilelang.language` 默认转出 CUDA 方言，CUDA 的 `copy` 覆盖 common 的实现入口，并增加 CUDA 相关关键字。因此索引记录公开别名与真实定义，不单凭函数短名匹配。

| 内容层 | 知识来源 | 用途 |
| --- | --- | --- |
| 编程模型与语法 | programming_guides、get_started、layout 类说明 | 理解 tile、线程映射、内存作用域、循环与流水线 |
| 公开 API | language、CUDA/ROCm/CPU/Metal/WebGPU 方言、jit、layout、profiler | 查签名、参数、返回值、公开导出关系 |
| DSL 指令 | copy/gemm/reduction/builtin 源码和 instructions 文档 | 区分同步、异步、等待、约束与硬件说明 |
| 算子模式 | GEMM、attention、softmax、layout、pipeline 等目录 | 查可复用的实现结构 |
| 编译器与后端 | engine、transform、tileop、src/op、src/transform、各后端 codegen | 从 pass 名或错误信息定位实现 |
| 示例与教程 | examples 中的 kernel 构造函数、教程语义小节 | 生成参考、理解完整调用结构 |

`layer` 区分用户层与实现层。`visibility` 区分公开 API、模块内定义、内部实现、文档与示例。内部 C++ 节点不会被描述成可以直接调用的 `T.*`。

## 3. 一个知识单元里有什么

每个单元都有用户要求的八类字段，并补充了版本与解释所需的信息：

| 字段 | 含义 |
| --- | --- |
| `id` | 稳定 K 编号，由类别、语义身份和路径生成；不使用行号作为身份 |
| `category`、`name` | API、instruction、concept、operator、compiler 或 example，以及完整名称 |
| `description`、`when_to_use` | 源码说明或明确标注的结构性使用提示 |
| `parameters`、`signature`、`returns` | 参数种类、注解、默认值、docstring 参数说明及可提取的返回注解 |
| `examples` | 关联示例的 K 编号与来源，或文档原有代码块 |
| `related_concepts` | 主题和关联知识单元 |
| `source_location` | 仓库相对路径、开始行和结束行 |
| `keywords` | 领域术语、路径信息和用于搜索的词 |
| `aliases`、`visibility`、`layer` | `T.copy` 等公开别名，以及使用层次 |
| `content`、`context`、`dependencies` | 完整语义主体、示例 imports/常量、依赖 helper 或导出文件 |
| `source_revision`、`source_hash` | Git 版本与完整源文件 SHA-256 |
| `constraints`、`hardware_mapping` | 从说明中提取的原文约束和硬件段落；空值表示没有提取到 |
| `targets`、`evidence_quality`、`cautions` | 来源方言、证据类型及使用边界 |
| `operator_structure` | 从示例 AST 提取的控制流、分配、数据传输、计算和同步调用及其参数 |

Python 源码通过 `ast` 解析为语法树。`ast` 能识别函数、参数、装饰器和嵌套语句，无需导入 TileLang，也不会运行下载、编译或初始化 GPU 的代码。

导出分析使用有界的不动点传播：重复传播模块之间的 import / `__all__` 信息，直到结果稳定，最多 16 轮。这样既处理循环导出，也避免递归路径爆炸。动态或外部依赖没有解析到时进入构建诊断，不伪造定义。

## 4. 如何拆分，如何控制长度

- **API**：函数、类和方法为单元，保留完整主体与装饰器。公开的 callable proxy 会关联实际 `__call__`，例如 `T.Tensor`。
- **概念**：Markdown 围栏外的标题小节，以及 Layout/Fragment 等类的语义说明。代码块中的 `#` 注释不会被误认成章节标题。
- **示例**：包含 `T.Kernel` 或 `T.prim_func` 的顶层构造函数为单元，嵌套 kernel、循环和返回语句完整保留。imports、常量与 helper 依赖单独列出。
- **编译器**：Python pass/lowering 函数、C++ 命名 class/struct/函数。C++ 扫描会忽略注释和字符串中的括号，并区分同名重载；它不是完整的 Clang 解析器。

保存的 `content` 不按文件大小切断。长度限制发生在**传递给模型**时：搜索默认返回摘要，`include_source=true` 可携带不超过 4000 字符的完整主体及依赖上下文；预算不足则明确回退摘要。阅读工具返回带行号的分页。`truncated=true` 意味着还没读完，`next_line` 指向下一页。不能拿第一页冒充完整示例。

未知的返回类型、动态参数或设备限制保持未知。结构抽取不会自动证明示例独立可运行，也不会把源码里的 benchmark 数值当成本机实测。

## 5. 五类索引怎样选择

| 问题 | 主要索引 | 示例 |
| --- | --- | --- |
| 具体函数/类/模块 | API，辅以 Concept | `T.Pipelined` 的 `num_stages` 参数 |
| DSL 概念 | Concept，辅以 API / Operator | fragment 布局与线程映射 |
| 生成或优化 kernel | Operator / Example，补 API / Concept | 生成 float16 GEMM |
| 编译器错误、pass、codegen | Compiler，补 API / Concept | `LayoutInference` 报错 |
| 目标选择 | Concept，补 Compiler / API | Metal 或 HIP target 怎么写 |

索引使用 SQLite FTS5。它把词映射到相关记录，使用 BM25 和字段权重召回；再结合精确符号、问题类型、算子类别、来源层次和目标过滤排序。中文领域词组显式映射到英文源码术语，例如“流水线”对应 pipeline / pipelined。

精确符号会优先查导出表，模块入口与同名可调用对象分开排序。明确查询不存在的 API 时返回 `no_match` 和 `missing_symbols`，不会仅因为名字里含有 copy 或 kernel 就用相似结果冒充。

这套实现不调用 embedding 服务，不依赖向量数据库。FTS5 的词法方法可解释、能处理源码符号；开放式语义改写仍可能漏召回，所以保留显式索引选择、继续查询和原文工具。

## 6. 上下文预算

| 限制 | 当前值 |
| --- | --- |
| 每个索引的候选上限 | 100 |
| Top-K | 默认 5，最多 10 |
| 单次知识返回字符数 | 默认 10000，可设 1500～20000 |
| 自动预检索预算 | Top-K=3，`min(7000, context_chars // 3)` |
| Agent 总上下文默认预算 | 48000 字符，包含规则、工具说明、历史和本轮反馈 |

预算包含序列化 JSON 与证据编号。字符数不是模型 tokenizer 算出的精确 Token 数。普通文件工具原有的大小限制和 Agent 总预算继续生效。

扩库时重新构建倒排索引；查询仍只访问选中的索引和有限候选。源码、JSONL、整张语义图以及历史运行记录都不会整体塞进 Prompt。扩库测试只证明指定场景的隔离与上限，不代表任意新内容加入后所有问题的相关性都不会下降。

## 7. 同项目分发与使用

项目布局如下，`data/tilelang` 位于 Python 包内，因此源码项目和 wheel 安装都能自动找到它，启动位置和工作区选择不会影响查找：

```text
src/kernellens/
├── knowledge/               # 检索与构建程序
└── data/tilelang/            # 用户直接使用的知识包
    ├── index.sqlite3        # 完整知识正文、参数、关系及五类索引
    ├── manifest.json        # 来源、记录统计及交付哈希
    ├── README.md
    ├── LICENSE              # 上游许可原文
    └── THIRDPARTYNOTICES.txt
```

普通用户在 KernelLens 项目根目录运行：

```bash
# 仅查询/校验知识，不需要模型配置
uv run --locked python -m kernellens.knowledge validate
uv run --locked python -m kernellens.knowledge search 'T.copy 的同步语义'
# 使用检索返回的真实 K 编号
uv run --locked python -m kernellens.knowledge read K_REPLACE_WITH_RETURNED_ID

# 配置模型 API 后，使用默认随包知识
uv run --locked kernellens
# 可选：关闭 RAG
uv run --locked kernellens --no-knowledge
```

随包目录自动定位；`--knowledge` 或 `.env` 的 `KERNELLENS_KNOWLEDGE_DIR` 可显式覆盖路径，空值可关闭 RAG。显式选择的包或默认包损坏时报告错误，不自动切换为无知识模式。不覆盖路径时即采用默认知识包。

仅维护者更新内容时需要 TileLang 源码：

```bash
uv run --locked python -m kernellens.knowledge build --repo tilelang
uv run --locked python -m kernellens.knowledge bundle \
  --knowledge tilelang/tilelang_knowledge \
  --output src/kernellens/data/tilelang
```

导出前校验原始知识与源码；导出后校验独立快照，再替换既有包。SQLite 已保存完整记录，随包版不重复包含 JSONL 和 MCP 视图。原始构建仍产出完整 MCP 交付，供维护者工具使用。

外层 Git 继续忽略独立 `tilelang/` 克隆；**`src/kernellens/data/tilelang/` 应与 KernelLens 代码一起提交和分发**。普通用户不需要重新构建。当前知识包约 31 MiB，整个 wheel 压缩后约 6.4 MiB。

## 8. 来源变化与安全边界

加载时检查索引哈希与格式。默认 snapshot 模式从包内正文读取，源码路径/哈希是构建时的出处元数据，不声称核对了用户机器上的源码；工具证据指向实际知识包文件，原始源码位置另外记录。校验命令还检查包文件哈希、记录和行范围。

显式选择 source 模式时，继续核对原始源文件及导出文件哈希；缺失或变化会要求重建。两种模式的知识都不会自动随外部仓库变化而更新。

知识库只能通过只读知识工具访问。普通 `read_file`、`write_file` 等仍受任务工作区边界约束。知识内容属于材料，里面的文本不能改变工具权限或用户要求。SQLite 会话、模型凭证和私有运行数据没有被收入知识库。

这些哈希用于发现内容变化和损坏，不等于对恶意发布者的数字签名认证。知识库应从用户信任的本地源码构建。

## 9. 验证能证明什么

- **抽取/导出校验**：构建时核对源文件哈希、行范围与正文；随包模式校验快照完整性，来源信息保留为元数据。
- **独立安装验证**：安装 wheel 后禁止访问原 TileLang 克隆与原 KernelLens 源码，仍可默认检索、阅读、核对 API 并完成本地替身 Agent 流程。
- **检索评估**：固定的 28 个跨类别问题召回预期来源，并满足预算与候选上限。评估集是可见回归集，不是模型准确率或盲测成绩。
- **工程测试**：循环导出、API 覆盖、语义边界、未知符号、过期来源、分页、扩库噪声、工具边界和 Agent 首次预检索。
- **生成静态检查**：公开导出与关键字名可被源码确认；识别冲突和未知情况；另检查可识别的局部 fragment 是否在 GEMM 前初始化，漏掉清零会阻止交付。分支、辅助函数和动态 clear 标志无法确定时保留 inconclusive。没有执行参数类型检查、TileLang lowering 或 GPU 编译。
- **真实模型验收**：由显式脚本检查模型是否实际使用知识工具，并保存候选及静态检查结果。完整记录见 [RAG 验证记录](rag-validation.md)，包括失败、修正和未完成的签名/GPU 检查。不能用 HTTP 成功代替算子正确。

```bash
# 离线检索回归
uv run --locked python scripts/evaluate_knowledge.py \
  --output .kernellens/rag-evaluation/current.json

# 显式真实调用，可能计费；默认只运行解释任务
uv run --locked python scripts/smoke_rag_live.py --run-live --case diagnose
```

固定尺寸 GEMM 的声明检查支持参数注解、函数体内的 `A: T.Tensor(...)`、`T.empty(...)`、字符串 dtype 和 `T.float16` 等对象写法。`T.const(...)` 的动态尺寸仍标为未知，不从用户要求反填为已验证尺寸。

动态包装导出（例如当前版本的 `T.ceildiv`）可能只有可确认的导出来源，没有可提取的完整签名。这类调用标为 `inconclusive`；已知关键字冲突标为 `failed`。

真实验收脚本的预算高于日常 CLI 默认值，具体配置和全部尝试用量见 [验证记录](rag-validation.md)；不能把验收成功解读为任意任务都能在默认预算内一次完成。

真实生成/优化仍需要对应 GPU 上的编译、参考数值对比和一致口径的重复计时。当前 Mac 上的知识库构建与检查，没有完成这些硬件验证。

## 10. 阅读代码的顺序

1. [schema.py](../src/kernellens/knowledge/schema.py)：先看一个知识单元的输入输出契约。
2. [extract.py](../src/kernellens/knowledge/extract.py)：看如何识别语义边界与导出来源。
3. [build.py](../src/kernellens/knowledge/build.py)：看 JSONL、五类索引和兼容视图如何生成。
4. [terms.py](../src/kernellens/knowledge/terms.py)、[search.py](../src/kernellens/knowledge/search.py)：看问题路由、排序、来源校验与预算。
5. [application.py](../src/kernellens/application.py)、[registry.py](../src/kernellens/tools/registry.py)：看预检索和模型工具调用如何接回 Agent Loop。
6. [contracts.py](../src/kernellens/knowledge/contracts.py)、[review.py](../src/kernellens/review.py)：看哪些事实能由程序验证，哪些仍待实际运行。
