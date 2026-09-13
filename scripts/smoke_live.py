#!/usr/bin/env python3
"""Explicit opt-in live API acceptance. Credentials are never printed."""

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from kernellens.application import AgentApplication
from kernellens.config import load_settings
from kernellens.domain.task import TaskType
from kernellens.tools.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--case",
        choices=["diagnose", "generate", "optimize", "all"],
        default="diagnose",
    )
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    settings = replace(
        load_settings(env_file=args.env_file),
        max_decisions=12,
        max_run_seconds=480,
        timeout=90,
        max_output_tokens=6000,
        gpu="NVIDIA A100",
    )
    settings.require_model()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = args.workspace or Path(".kernellens") / "live-validation" / stamp
    root.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(root)
    # All fixtures are non-sensitive, purpose-made test inputs.
    if not (root / "bug.py").exists():
        (root / "bug.py").write_text(
            "def mean(values):\n    return sum(values) / len(values)\n",
            encoding="utf-8",
        )
    app = AgentApplication(
        workspace, settings, emit=lambda s: print(s, file=sys.stderr, flush=True)
    )
    cases = [args.case] if args.case != "all" else ["diagnose", "generate", "optimize"]
    outcomes = []
    try:
        for case in cases:
            if case == "diagnose":
                goal = "读取 bug.py，诊断 mean([]) 为什么报错。将有证据的解释与修复建议用 write_file 保存为 artifacts/diagnosis.md，然后引用证据提交。不要执行代码。"
            elif case == "generate":
                goal = "生成基础 TileLang GEMM 候选 artifacts/gemm.py：M=N=K=128，A/B/C float16，累加 float32，行主序，NVIDIA A100/SM80。你可以采用合理的 block 默认值并说明。再保存 artifacts/gemm-validation.md，给出与 PyTorch 参考对比、容差、预热与重复计时的服务器验证步骤。本工作区没有 TileLang 源码，明确 API 尚未核对，不要声称 GPU 已运行或性能提升。实际保存候选并检查语法后交付，不再询问参数。"
            else:
                goal = "优化现有 artifacts/gemm.py 的基础 GEMM：先读取 baseline，保持计算契约，选择一项 tile 或流水线参数改动，另存 artifacts/gemm-optimized.py。将瓶颈假设、参数改变、对照实验和尚未验证的 API 写入 artifacts/optimization.md；语法检查后提交。不要宣称已经提速，不要执行 GPU 代码。"
            result = app.run(
                app.store.create_session("live-" + case), goal, TaskType(case)
            )
            expected = {
                "diagnose": ["artifacts/diagnosis.md"],
                "generate": ["artifacts/gemm.py", "artifacts/gemm-validation.md"],
                "optimize": [
                    "artifacts/gemm-optimized.py",
                    "artifacts/optimization.md",
                ],
            }[case]
            passed = result.status == "completed" and all(
                (root / path).is_file() and (root / path).stat().st_size > 0
                for path in expected
            )
            contract_checks = []
            for step in app.store.steps(result.run_id):
                observation = step.get("observation")
                if observation and observation["status"] == "succeeded":
                    report = json.loads(observation["content"])
                    if "gemm_contract" in report:
                        contract_checks.append(report["gemm_contract"])
            if case in {"generate", "optimize"}:
                passed = (
                    passed
                    and bool(contract_checks)
                    and contract_checks[-1]["status"] == "passed"
                    and contract_checks[-1]["declared"].get("C") == "float16"
                )
            outcomes.append(
                {
                    "case": case,
                    "status": result.status,
                    "passed": passed,
                    "run_id": result.run_id,
                    "report": result.report_path,
                    "usage": result.usage,
                    "artifacts": list(result.artifacts),
                    "contract_checks": contract_checks,
                }
            )
            print(json.dumps(outcomes[-1], ensure_ascii=False), flush=True)
            if not passed:
                break
        receipt = {
            "workspace": str(root.resolve()),
            "outcomes": outcomes,
            "hardware": "not_run",
        }
        (root / "acceptance.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return (
            0
            if len(outcomes) == len(cases) and all(item["passed"] for item in outcomes)
            else 1
        )
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
