# KernelLens CLI 使用手册

## 安装和配置

在项目根目录运行 `uv sync --locked`。直接运行依赖为 Pydantic 2.13.5 和 Textual 8.2.8（终端界面）；HTTP、SQLite 和静态分析使用 Python 3.12 标准库；uv.lock 固定全部依赖。项目和安装包已包含 TileLang 知识包，无需 clone TileLang、下载额外知识或设置本地源码路径。

```dotenv
base_url=https://your-provider.example/v1
model=your-model-id
api_key=your-private-key
```

复制 `.env.example` 为 `.env` 后填写，已有 `.env` 无需覆盖。dotenv 解析支持引号、注释和 `export`，值不执行 shell、不做变量展开。引号内的 `#` 保留。配置加载优先级：显式 CLI 参数 > 环境变量 > 指定/发现的 dotenv > 默认值。

dotenv 从启动目录向上查找；可编辑安装还会查找本项目根目录。`--env-file` 可以显式指定。环境变量仍优先于该文件；若配置不符合预期，核对 `KERNELLENS_*`、`OPENAI_*` 和小写变量。选择工作区不会加载该目录中的另一份密钥。

| 配置 | 默认值 | 含义 |
| --- | ---: | --- |
| KERNELLENS_MAX_DECISIONS | 20 | 每轮行动/决策尝试数，包括非法提议和审核拒绝 |
| KERNELLENS_TIMEOUT | 60 | 单次 HTTP 阻塞操作超时，秒 |
| KERNELLENS_MAX_RUN_SECONDS | 300 | 在请求边界检查的运行时间预算；请求 timeout 会按剩余时间缩小 |
| KERNELLENS_MAX_OUTPUT_TOKENS | 4096 | 每个请求的输出 Token 上限 |
| KERNELLENS_MAX_TOTAL_TOKENS | 60000 | 已知累计用量与下一次输出预留的准入门槛 |
| KERNELLENS_CONTEXT_CHARS | 48000 | 模型消息及工具 Schema 的字符上限 |
| KERNELLENS_MAX_RETRIES | 2 | 一个 HTTP 请求最多额外重试次数 |
| KERNELLENS_TOOL_MODE | native | native function calling 或 json 行动模式 |
| KERNELLENS_KNOWLEDGE_DIR | 随包目录 | 可选覆盖；显式空值关闭 RAG |
| KERNELLENS_GPU | 空 | 可选的默认执行 GPU 型号；缺失时按任务需要询问 |

Token 门槛不是供应商账单硬上限：输入 Token、未返回 usage 的失败尝试和服务端计费存在不确定性。缺失用量显示 unknown；费用为 null，不以零冒充。每轮显示 HTTP 请求数与可用 Token 统计。超时限制作用于网络操作和请求边界，不承诺操作系统级强制终止整个进程。

## 交互流程

正常终端中运行 `uv run --locked kernellens` 默认打开全屏 TUI，工作区为启动目录。输入 `/` 联想命令、↑↓ 选择、Tab 补全；Enter 发送、Ctrl+J 换行、Ctrl+O 选择工作区；右侧显示步骤与生成文件。可显式使用 `--tui`，详见 [终端界面手册](tui.md)。

以下提示符、`/paste` 和 Ctrl+C 行为描述原逐行界面。运行 `uv run --locked kernellens --plain`，选择一个已存在目录。路径可包含中文或空格。无效路径会提示重新选择；输入 q 或 Ctrl+D 退出。

直接输入需求后，屏幕显示决策序号、工具执行状态和最终报告。可明确选择任务类型：

- `/generate`：生成 Python/TileLang 候选，保存文件，检查当前版本的语法和可识别的计算契约。
- `/optimize`：先读取 baseline，另存候选，保持可识别的 shape/dtype 契约，说明假设和实验。
- `/diagnose`：读取代码、源码材料或日志，引用证据调查和解释。一般解释性问题也走此路径。

自然语言会做轻量任务类型识别。需要严格指定时使用上述命令或 `--task`。

| 交互命令 | 用途 |
| --- | --- |
| /help | 查看全部命令 |
| /paste | 仅逐行界面：多行输入，以单独一行 /end 结束 |
| /workspace [路径] | 选择或切换工作区，创建该工作区的新会话 |
| /new | 当前工作区新建会话 |
| /sessions | 列出最近会话 |
| /resume ID | 用完整 ID 或唯一前缀恢复会话 |
| /history | 显示最近用户输入和回答 |
| /runs | 查看本会话每轮状态 |
| /trace [ID] | 查看运行的行动、反馈和错误 |
| /status | 查看工作区、模型与预算配置，不显示密钥 |
| /files、/open | 仅 TUI：浏览工作区文件和只读预览 |
| /gpu [型号] | 查看或设置当前会话的目标 GPU；/gpu clear 清空 |
| /exit | 退出，保留已写入的记录 |

请求补充信息后直接输入答案。应用将上一轮未完成的目标和本次补充一起交给新一轮，保留会话，使用新的次数预算。失败、中断或预算耗尽后输入“继续”或“重试”，同样重新读取当前文件后推进原目标。它不是自动重放旧 HTTP 请求或写入动作。

逐行界面中，Ctrl+C 中断运行时，已保存的文件和步骤保留，状态记为 interrupted；可继续交互。输入提示符下 Ctrl+C 仅取消当前输入。进程被强制结束后，下一次打开工作区会把已确认原进程不存在的 running 记录标为 interrupted。不会恢复到一次写入的中间位置。

TUI 使用 Ctrl+Q 退出；任务运行中按下会在本轮完成并保存后退出，当前任务仍会继续执行。TUI 没有立即停止按钮，也不改变 Runtime 的中断逻辑。

## 目标 GPU

GPU 指实际执行算子的设备。Agent 所在的 Mac、参考示例中的硬件都不自动成为目标。

```text
你> /generate 生成基础 GEMM，M=N=K=128，A/B/C float16，累加 float32。
Agent> 这个算子准备在哪个 GPU 型号上运行？……
[waiting_input] 请求 0 次；Token 0
你> NVIDIA A100 80GB
```

补充后保留原始生成任务及 shape/dtype 约束，进入检索和模型流程；后续必要参数仍可能由模型询问。也可以事先用 `/gpu NVIDIA A100 80GB` 设置，或在需求里写“目标 GPU：NVIDIA A100”。常见型号可从自然语言识别；其他型号可用 `/gpu 型号`、`--gpu "型号"` 或明确的 `GPU: 型号` 填写。型号字符串不作为已通过设备支持验证的证明。

```bash
uv run --locked kernellens -w /path/to/workspace --gpu "NVIDIA A100" \
  --task generate -p '生成基础 GEMM，M=N=K=128，A/B/C float16，累加 float32' --json

# 单次命令缺少型号时返回码为 2；使用返回的 session_id 接着回答
uv run --locked kernellens -w /path/to/workspace --resume SESSION_ID -p 'NVIDIA A100' --json
```

当前需求中明确声明的 GPU 优先；其次是会话已保存的型号；最后是 `KERNELLENS_GPU` 默认值。显式 `--gpu` 会覆盖本次打开的会话值。`/gpu` 修改保存在当前工作区的当前会话，重启后 `/resume` 可恢复；`/new` 和新工作区不继承旧会话值，只使用启动配置的默认值。`/gpu clear` 将当前会话设为未知，旧目标文字和默认配置不会重新填回。设置命令本身不运行任务，等待中的任务输入“继续”即可。

生成和优化必须先有具体型号，仅填写 CUDA、NVIDIA 或“不知道”仍会询问。若设备尚未确定，可先用 `/diagnose` 讨论与设备无关的概念。常见编译/运行错误和性能诊断也有程序输入检查；其他依赖硬件的诊断由模型根据材料调用 `request_input`。普通文件阅读、API 语义解释不强制询问 GPU。

GPU 记录包含 `model`、`backend`、`source`，传入模型上下文、每轮 JSON 结果和报告。常见厂商/型号对应的后端用于预检索及后续知识搜索的默认过滤；未知后端不强行过滤。允许明确的跨后端对比查询。过滤只排除已标注为其他后端的条目，无目标标签的通用知识仍可返回；不会自动验证显存容量、SM 架构或特殊指令支持，使用前仍需核对来源与实际设备。

## 文件与工具

提供 list_files、read_file、search_text、write_file、check_python、read_report、compare_reports；模型还可提出 request_input 和 finish。

默认加载随项目分发的知识包，提供 `search_knowledge`、`read_knowledge`。`--knowledge` 或 `KERNELLENS_KNOWLEDGE_DIR` 可指定其他知识库；`--no-knowledge` 关闭本次 RAG。相关问题在首次模型请求前自动预检索；`/trace` 中 `decision: 0` 是程序检索事件，后续正整数仍是模型决策。`/status` 显示知识库路径、加载模式和来源信息。

- 原生工具调用保留 call ID 与结果配对；一次多工具提议会被整体拒绝并反馈，要求模型顺序调用，不执行其中的部分动作。
- 所有工具参数使用严格 Schema，拒绝未知字段。失败反馈可进入下一轮，修正仍计入预算。
- 文件路径解析到当前工作区。凭证、`.env*`、`.git`、依赖、内部记录被排除；工具不跟随符号链接。
- 读取上限 1 MB，普通文件及 UTF-8 文本；片段、搜索、遍历和反馈都有数量上限。不能把截断结果当完整枚举。
- 写入内容上限 200 KB。新文件不得覆盖已存在文件；覆盖需提供 read_file 给出的 SHA-256，保存旧内容备份后原子替换。
- write_file 不执行代码，不运行 shell。工具权限不是对恶意本机并发进程的完整 OS 沙箱承诺。

随包知识采用 snapshot 模式，读取内置正文并校验索引完整性，不访问外部源码。维护者仍可按 [RAG 说明](tilelang-rag.md) 构建 source 模式知识库，检查本地源码变化。两种模式都不扩大普通文件工具的范围；关闭知识检索后仍可搜索工作区原文。知识快照与有限静态检查不等于通过硬件验证。

## 静态声明和验收边界

`check_python` 使用 AST 解析，不 import 或执行候选。可从简单常量、函数默认值、A/B/C Tensor/Buffer 声明和累加缓冲区中读取 GEMM 维度和 dtype。

当前明确目标识别支持 `M=N=K=128`、`M=128`/`N=128`/`K=128`、`A/B/C float16`、`A/B float16`、`C float16`、`累加 float32` 等形式。未知动态表达式标记 inconclusive。复杂语义、布局、容差和设备适配仍需要源码依据及服务器验证；静态声明通过不能证明乘法计算正确。

生成任务的显式约束不通过会阻止 finish。优化任务从首次可识别的 baseline 读取计算声明，并检查候选的一致性。API 参数和 dtype 的语义不能只凭代码注释确认。

报告审核还检查本轮证据 ID 是否存在、候选仍对应当前哈希、语法检查是否属于同一版本，以及优化是否读取了不同版本 baseline。它不是自然语言真伪的完整证明；程序生成的检查摘要是验证状态的依据。

## 服务器报告反馈

使用 `examples/verification-report.example.json` 的形状整理真实回传结果。候选路径相对工作区；SHA-256 必须属于实际测试的代码。保留原始日志、环境、workload、测量方法和每个重复样本。

`read_report` 保留 user_report 来源并核对候选。`compare_reports` 要求两边候选均匹配、environment/workload/measurement 均存在且一致、correctness 为 passed、至少三个正且有限的 latency_ms 样本，才计算中位数比值。

该比值只描述用户提供的样本，不能认证其来源，也不证明统计显著性或对其他 workload 的收益。API 证据、GPU 编译、数值正确性与性能始终分开。

## 单次命令、输出和返回码

```bash
uv run --locked kernellens -w /path/to/workspace \
  --task diagnose --prompt '读取 compile.log 并解释错误' --json
```

stdout 为一个 JSON 对象：run_id、session_id、status、answer、report_path、usage、artifacts、gpu。进度写入 stderr。report_path 与 artifacts 相对工作区。

| 返回码 | 含义 |
| --- | --- |
| 0 | 任务完成或正常退出 |
| 1 | 配置/执行错误或预算耗尽 |
| 2 | 单次任务等待补充输入；也用于 argparse 参数错误 |
| 130 | 单次运行被 Ctrl+C 中断 |

## 故障处理

- `--doctor`：离线核对 Python、包导入位置、模型配置是否齐全。包路径应属于当前 checkout，不能仍指向复制前的旧目录。
- 环境复制后的旧路径：在本项目运行 `uv sync --locked --reinstall`，再运行 `--doctor`，不要靠永久修改 PYTHONPATH 掩盖安装问题。
- `--check-api`：显式进行一次小型真实请求，最多 128 输出 Token，不自动重试；可能计费。
- HTTP 400：检查 endpoint、model 和工具支持；必要时 `--tool-mode json`。
- HTTP 401/403：核对 Key 与模型权限。
- HTTP 402：核对服务端付费/额度状态；应用不自动重试该错误。
- HTTP 429/500/502/503/504、连接超时：有限退避重试；仍失败则保存步骤并返回明确错误。
- 输出截断：适当提高 max_output_tokens 或拆分文件/任务。
- 文件冲突：先重新读取当前版本，不直接覆盖。
- 记录保存失败：CLI 返回错误；先检查磁盘空间、权限或 SQLite 文件，不能把这种运行当作已可靠保存。

## 安装与维护检查

仓库内可执行的源码、知识包、图源和构建检查见 [验证说明](validation.md)。完整自动测试与真实验收脚本由维护者在本地保留；克隆后的运行不依赖它们。

`--check-api` 只验证一次模型连接，不证明生成或优化效果。真实候选仍需在目标 GPU 上独立检查与测量。
