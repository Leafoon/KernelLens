import json
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from kernellens.constraints import (
    check_gemm_constraints,
    check_gemm_initialization,
    declared_gemm_signature,
)
from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus, ToolObservation
from kernellens.knowledge.contracts import check_calls
from kernellens.knowledge.search import KnowledgeBase
from kernellens.security import Redactor
from kernellens.tools.arguments import (
    CompareReportsArguments,
    FinishArguments,
    ListFilesArguments,
    ReadFileArguments,
    ReadKnowledgeArguments,
    ReadReportArguments,
    RequestInputArguments,
    SearchArguments,
    SearchKnowledgeArguments,
    WriteFileArguments,
)
from kernellens.tools.workspace import Workspace, WorkspaceError


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[BaseModel]
    execute: Callable

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(
        self,
        workspace: Workspace,
        run_id: str,
        redactor: Redactor,
        constraints: dict | None = None,
        *,
        optimizing: bool = False,
        knowledge: KnowledgeBase | None = None,
        target: str = "",
    ):
        self.workspace, self.run_id, self.redact = workspace, run_id, redactor
        self.constraints = constraints or {}
        self.optimizing = optimizing
        self.knowledge = knowledge
        self.target = target
        self.knowledge_reads: dict[str, dict] = {}
        self.baseline_contract: dict = {}
        self.tools: dict[str, ToolDefinition] = {}
        self.evidence: list[dict] = []
        self.artifacts: dict[str, dict] = {}
        self.checks: dict[str, dict] = {}
        if knowledge is not None:
            self.register(
                ToolDefinition(
                    "search_knowledge",
                    "按问题类型检索已配置的 TileLang API/概念/示例/编译器/算子知识索引；返回有界摘要、来源和 unit_id。优先于扫描整个源码仓库。",
                    SearchKnowledgeArguments,
                    self.search_knowledge,
                )
            )
            self.register(
                ToolDefinition(
                    "read_knowledge",
                    "按 unit_id 读取源码知识单元及参数、依赖；truncated 时用 next_line 继续，完整参考后再生成。不会执行代码。",
                    ReadKnowledgeArguments,
                    knowledge.read,
                )
            )
        self.register(
            ToolDefinition(
                "list_files",
                "列出工作区内文件；默认排除凭证、依赖与内部运行记录。",
                ListFilesArguments,
                workspace.list_files,
            )
        )
        self.register(
            ToolDefinition(
                "read_file",
                "读取 UTF-8 文件片段，返回行号与整个文件 SHA-256，可用于证据和覆盖校验。",
                ReadFileArguments,
                workspace.read_file,
            )
        )
        self.register(
            ToolDefinition(
                "search_text",
                "在工作区按字面子串搜索代码和文档，返回路径、行号与 SHA-256。",
                SearchArguments,
                workspace.search_text,
            )
        )
        self.register(
            ToolDefinition(
                "write_file",
                "保存候选或文档到工作区；优先 artifacts/。覆盖文件必须给出读取的 expected_sha256，程序先备份。",
                WriteFileArguments,
                lambda **kw: workspace.write_file(**kw, run_id=run_id),
            )
        )
        self.register(
            ToolDefinition(
                "check_python",
                "检查 Python 语法、明确的 GEMM 声明；配置知识库时补充公开 API 关键字及局部累加器初始化检查。不会执行代码或证明 GPU 正确性。",
                ReadReportArguments,
                self.check_python,
            )
        )
        self.register(
            ToolDefinition(
                "read_report",
                "读取用户提供的 JSON 执行报告；核对 candidate_path/candidate_sha256，保留来源与未验证边界。",
                ReadReportArguments,
                workspace.read_report,
            )
        )
        self.register(
            ToolDefinition(
                "compare_reports",
                "对比两份用户执行报告：核对代码 SHA、环境、工作负载、测量方法与正确性，再计算 latency_ms 中位数比值。不会实际执行 GPU。",
                CompareReportsArguments,
                workspace.compare_reports,
            )
        )

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self.tools:
            raise ValueError("工具名称重复")
        self.tools[tool.name] = tool

    def search_knowledge(self, **arguments) -> dict:
        # Explicit cross-backend searches remain possible for comparisons.
        arguments["target"] = arguments.get("target") or self.target
        return self.knowledge.search(**arguments)

    def check_python(self, path: str) -> dict:
        result = self.workspace.check_python(path)
        if self.knowledge and result.get("syntax") == "passed":
            _, data = self.workspace.read_bytes(path)
            result["tilelang_api"] = check_calls(data.decode("utf-8"), self.knowledge)
            result["gemm_initialization"] = check_gemm_initialization(
                data.decode("utf-8")
            )
        if self.constraints and result.get("syntax") == "passed":
            _, data = self.workspace.read_bytes(path)
            result["gemm_contract"] = check_gemm_constraints(
                data.decode("utf-8"), self.constraints
            )
        return result

    def schemas(self) -> list[dict]:
        result = [tool.schema() for tool in self.tools.values()]
        for name, description, arguments in (
            (
                "request_input",
                "缺少必要输入时提出具体问题，暂停本轮等待用户回答。",
                RequestInputArguments,
            ),
            (
                "finish",
                "提交最终回答：引用证据 E1 等、产物路径、验证状态和后续步骤。",
                FinishArguments,
            ),
        ):
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": arguments.model_json_schema(),
                    },
                }
            )
        return result

    def __call__(self, action: CallToolAction) -> ToolObservation:
        try:
            if action.tool_name == "__protocol_error__":
                raise WorkspaceError(
                    "模型行动格式错误: "
                    + str(action.arguments.get("message", "请按 Schema 返回一个行动"))
                )
            if action.tool_name not in self.tools:
                raise WorkspaceError("未知工具，请使用已提供的工具列表")
            tool = self.tools[action.tool_name]
            arguments = tool.arguments.model_validate(dict(action.arguments))
            result = tool.execute(**arguments.model_dump())
            if (
                self.optimizing
                and not self.baseline_contract
                and action.tool_name == "read_file"
                and result.get("path", "").endswith(".py")
            ):
                _, raw = self.workspace.read_bytes(result["path"])
                try:
                    signature = declared_gemm_signature(raw.decode("utf-8"))
                except SyntaxError:
                    signature = {}
                if all(name in signature for name in ("A", "B", "C")):
                    self.baseline_contract = signature
                    self.constraints = signature | self.constraints
                    result["baseline_contract"] = self.constraints
            evidence_id = f"E{len(self.evidence) + 1}"
            result = {"evidence_id": evidence_id, **result}
            is_knowledge = action.tool_name in {"search_knowledge", "read_knowledge"}
            if is_knowledge:
                for _ in range(3):
                    result["context_chars"] = len(
                        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                    )
            self.evidence.append(
                {
                    "id": evidence_id,
                    "tool": action.tool_name,
                    "path": result.get("path"),
                    "sha256": result.get("sha256"),
                }
            )
            if action.tool_name in {"search_knowledge", "read_knowledge"}:
                if action.tool_name == "read_knowledge" and self.knowledge.repo:
                    self.evidence[-1]["path"] = str(
                        self.knowledge.repo / result["source_location"]["path"]
                    )
                    self.evidence[-1]["sha256"] = result["source_hash"]
                else:
                    self.evidence[-1]["path"] = str(
                        self.knowledge.directory / "index.sqlite3"
                    )
                    self.evidence[-1]["sha256"] = self.knowledge.manifest[
                        "delivery_hashes"
                    ]["index.sqlite3"]
                self.evidence[-1]["retrieval"] = {
                    "intent": result.get("intent"),
                    "indexes": result.get("indexes"),
                    "unit_ids": [r["id"] for r in result.get("results", [])]
                    or ([result["id"]] if result.get("id") else []),
                    "source_revision": result.get("source_revision"),
                    "delivery_mode": self.knowledge.delivery_mode,
                    "source_location": result.get("source_location"),
                    "source_hash": result.get("source_hash"),
                    "context_chars": result.get("context_chars"),
                    "status": result.get("status", "ok"),
                }
            if action.tool_name == "read_knowledge":
                location = result["source_location"]
                item = self.knowledge_reads.setdefault(
                    result["id"],
                    {"category": result["category"], "ranges": [], "complete": False},
                )
                item["ranges"].append(
                    (
                        result["start_line"],
                        (result.get("next_line") or location["end_line"] + 1) - 1,
                    )
                )
                end = location["start_line"] - 1
                for first, last in sorted(item["ranges"]):
                    if first <= end + 1:
                        end = max(end, last)
                item["complete"] = end >= location["end_line"]
            if action.tool_name == "search_knowledge":
                for unit in result.get("results", []):
                    if unit.get("source_complete"):
                        location = unit["source_location"]
                        self.knowledge_reads[unit["id"]] = {
                            "category": unit["category"],
                            "ranges": [(location["start_line"], location["end_line"])],
                            "complete": True,
                        }
            if action.tool_name == "write_file":
                self.artifacts[result["path"]] = result
            if action.tool_name == "check_python":
                self.checks[result["path"]] = result
            content = self.redact(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    **({"separators": (",", ":")} if is_knowledge else {}),
                )
            )
            if len(content) > 22000:
                content = json.dumps(
                    {
                        "evidence_id": evidence_id,
                        "truncated": True,
                        "preview": content[:21000],
                        "next": "缩小读取行数或搜索范围",
                    },
                    ensure_ascii=False,
                )
            return ToolObservation(action, ToolExecutionStatus.SUCCEEDED, content)
        except ValidationError as exc:
            errors = [
                {"loc": item["loc"], "type": item["type"]}
                for item in exc.errors(include_input=False)
            ]
            error = {"error": "invalid_arguments", "details": errors}
        except (
            WorkspaceError,
            OSError,
            UnicodeError,
            ValueError,
            RecursionError,
        ) as exc:
            error = {
                "error": type(exc).__name__,
                "message": self.redact(str(exc))[:1000],
            }
        return ToolObservation(
            action, ToolExecutionStatus.FAILED, json.dumps(error, ensure_ascii=False)
        )
