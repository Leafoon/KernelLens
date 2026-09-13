import re

from kernellens.domain.task import TaskType
from kernellens.knowledge.search import KnowledgeError
from kernellens.runtime.handlers import FinishRejected
from kernellens.tools.registry import ToolRegistry
from kernellens.tools.workspace import digest


class ReportReviewer:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def __call__(self, state, action) -> bool:
        registry = self.registry
        known = {item["id"] for item in registry.evidence}
        claimed = set(re.findall(r"\bE\d+\b", action.answer))
        if claimed - known:
            raise FinishRejected(
                "回答引用了本轮不存在的证据 ID，请引用实际工具返回的 evidence_id"
            )
        if state.request.task_type in {TaskType.GENERATE, TaskType.OPTIMIZE}:
            if registry.knowledge:
                for uid in registry.knowledge_reads:
                    try:
                        registry.knowledge._unit(uid)
                    except KnowledgeError as exc:
                        raise FinishRejected(
                            "知识来源在交付前已失效：" + str(exc)
                        ) from exc
                categories = {
                    item["category"]
                    for item in registry.knowledge_reads.values()
                    if item["complete"]
                }
                if "example" not in categories or not categories.intersection(
                    {"api", "instruction"}
                ):
                    raise FinishRejected(
                        "已有知识库：生成/优化前需要完整源码的 kernel 示例和至少一个 API 单元；source_complete=true 的预检索可计入，其他摘要必须 read_knowledge 阅读全文。"
                    )
            candidates = [
                item
                for path, item in registry.artifacts.items()
                if path.endswith(".py")
            ]
            if not candidates:
                raise FinishRejected(
                    "生成/优化任务需要用 write_file 保存 Python 候选，并进行 check_python"
                )
            matching_contract = False
            for candidate in candidates:
                check = registry.checks.get(candidate["path"], {})
                _, data = registry.workspace.read_bytes(candidate["path"])
                if (
                    digest(data) != candidate["sha256"]
                    or check.get("sha256") != candidate["sha256"]
                    or check.get("syntax") != "passed"
                ):
                    raise FinishRejected(
                        "候选需要针对当前文件版本通过 check_python；请修复或重新检查"
                    )
                contract = check.get("gemm_contract", {})
                if check.get("gemm_initialization", {}).get("status") == "failed":
                    raise FinishRejected(
                        "GEMM 使用了尚未初始化的局部累加器。按源码示例在 K 循环前 T.clear 累加器，再重新检查；不要在每次迭代清掉部分和。"
                    )
                if check.get("tilelang_api", {}).get("status") == "failed":
                    raise FinishRejected(
                        "候选中的 TileLang 关键字参数与当前源码签名冲突，请根据 check_python.tilelang_api 修正。"
                    )
                if registry.constraints:
                    current = contract.get("expected") == registry.constraints
                    passed = current and contract.get("status") == "passed"
                    matching_contract |= passed
                    # Helpers and test scripts need syntax checks, but need not
                    # themselves declare a GEMM. Recognizable kernels must match.
                    if (
                        set(contract.get("declared", {})) & {"A", "B", "C"}
                        and not passed
                    ):
                        raise FinishRejected(
                            "GEMM 的 shape/dtype 静态声明未满足当前契约。请查看 check_python 的 gemm_contract，修正后重新检查。"
                        )
            if registry.constraints and not matching_contract:
                raise FinishRejected(
                    "至少一个 GEMM 候选必须通过当前 shape/dtype 契约检查；请补充可静态解析的 Tensor 声明并运行 check_python。"
                )
            if state.request.task_type is TaskType.OPTIMIZE:
                baselines = [
                    item
                    for item in registry.evidence
                    if item["tool"] == "read_file"
                    and item["path"]
                    and item["path"].endswith(".py")
                    and item["sha256"] not in {c["sha256"] for c in candidates}
                ]
                if not baselines:
                    raise FinishRejected(
                        "优化需要读取已有 Python baseline，保留与候选不同的代码版本"
                    )
        if registry.evidence and not claimed:
            raise FinishRejected(
                "请在答案中引用本轮工具证据，如 [E1]，并说明已执行与未执行的检查"
            )
        return True
