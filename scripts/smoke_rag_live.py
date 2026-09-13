"""Explicit live RAG acceptance; uses synthetic tasks, no GPU execution."""

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from kernellens.application import AgentApplication
from kernellens.config import load_settings
from kernellens.domain.task import TaskType
from kernellens.knowledge import bundled_knowledge_dir
from kernellens.tools.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-live",
        action="store_true",
        required=True,
        help="明确发起可能计费的模型调用",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--knowledge", type=Path, default=bundled_knowledge_dir())
    parser.add_argument(
        "--case",
        choices=["diagnose", "generate", "optimize", "all"],
        default="diagnose",
    )
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    root = args.workspace or Path(".kernellens/rag-live") / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=True)
    settings = replace(
        load_settings(env_file=args.env_file),
        knowledge_dir=str(args.knowledge.resolve()),
        max_decisions=16,
        max_run_seconds=480,
        timeout=90,
        max_output_tokens=6000,
        max_total_tokens=120000,
    )
    app = AgentApplication(
        Workspace(root), settings, emit=lambda s: print(s, file=sys.stderr, flush=True)
    )
    cases = ["diagnose", "generate", "optimize"] if args.case == "all" else [args.case]
    goals = {
        "diagnose": "根据已配置的 TileLang 知识库，解释 T.copy 与 T.async_copy 的同步语义和等待要求。读取源码确认，用简洁中文回答并引用 E 证据、K 单元编号和源码位置。只做源码解释，不运行 GPU。",
        "generate": "生成基础 TileLang GEMM 候选 artifacts/gemm.py：M=N=K=128，A/B/C float16，累加 float32，行主序。测试目标是 NVIDIA A100/SM80（只是假设的验收目标，没有真实 GPU）。先用已配置知识库读取完整相关 kernel 示例和公开 API，适配源码用法。可采用合理 block 默认值；使用可静态解析的 M/N/K 常量或默认参数与 A/B/C Tensor 声明。保存并检查候选，简短说明来源和未运行的 GPU 验证，不再询问参数，不写额外基准脚本。",
        "optimize": "优化 artifacts/gemm.py 的 GEMM 候选：先读取 baseline，保持 M=N=K=128、A/B/C float16 和累加 float32 的计算契约；根据知识库的完整示例、API 和流水线说明，选择一项 tile 或流水线参数改动，保存到 artifacts/gemm-optimized.py 并检查。测试假设目标仍为 NVIDIA A100/SM80，没有实际 GPU。解释可证伪的优化假设，引用知识依据，不声称已经提速，不生成额外基准脚本。",
    }
    outcomes = []
    try:
        for case in cases:
            result = app.run(
                app.store.create_session("rag-live-" + case),
                goals[case],
                TaskType(case),
            )
            steps = app.store.steps(result.run_id)
            observations = [
                json.loads(s["observation"]["content"])
                for s in steps
                if s.get("observation") and s["observation"]["status"] == "succeeded"
            ]
            prefetch = steps[0].get("event") == "knowledge_prefetch" and bool(
                observations[0].get("results")
            )
            api = [o["tilelang_api"] for o in observations if "tilelang_api" in o]
            contracts = [
                o["gemm_contract"] for o in observations if "gemm_contract" in o
            ]
            initialization = [
                o["gemm_initialization"]
                for o in observations
                if "gemm_initialization" in o
            ]
            # Dynamic wrappers may have a confirmed export but no extracted
            # callable signature. Preserve that uncertainty; unknown exports or
            # actual keyword mismatches still fail this workflow acceptance.
            source_backed_calls = (
                bool(api)
                and bool(api[-1]["calls"])
                and all(
                    call.get("unit_id") and call["status"] != "failed"
                    for call in api[-1]["calls"]
                )
            )
            passed = result.status == "completed" and prefetch
            if case in {"generate", "optimize"}:
                path = (
                    root
                    / "artifacts"
                    / ("gemm.py" if case == "generate" else "gemm-optimized.py")
                )
                passed = (
                    passed
                    and path.is_file()
                    and source_backed_calls
                    and bool(contracts)
                    and contracts[-1]["status"] == "passed"
                    and bool(initialization)
                    and initialization[-1]["status"] == "passed"
                )
            outcome = {
                "case": case,
                "passed": passed,
                "status": result.status,
                "run_id": result.run_id,
                "report": result.report_path,
                "usage": result.usage,
                "prefetch": prefetch,
                "retrieval_steps": [
                    s["action"]["tool_name"]
                    for s in steps
                    if s.get("action")
                    and s["action"].get("tool_name")
                    in {"search_knowledge", "read_knowledge"}
                ],
                "api_checks": api,
                "api_signature_status": api[-1]["status"] if api else "not_run",
                "unresolved_api_symbols": sorted(
                    {
                        call["symbol"]
                        for call in (api[-1]["calls"] if api else [])
                        if call["status"] != "passed"
                    }
                ),
                "gemm_contracts": contracts,
                "gemm_initialization": initialization,
                "gpu_validation": "not_run",
                "acceptance_scope": "completed RAG workflow, source-backed calls and static GEMM contract; unresolved signatures and GPU correctness are not certified",
            }
            outcomes.append(outcome)
            (root / f"acceptance-{args.case}.json").write_text(
                json.dumps(
                    {"workspace": str(root.resolve()), "outcomes": outcomes},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in outcome.items()
                        if k not in {"api_checks", "gemm_contracts"}
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if not passed:
                break
    finally:
        app.close()
    return int(len(outcomes) != len(cases) or not all(o["passed"] for o in outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
