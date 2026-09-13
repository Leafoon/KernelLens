"""Source-grounded retrieval regression set; does not call an LLM or run kernels."""

import argparse
import json
import time
from pathlib import Path

from kernellens.knowledge import bundled_knowledge_dir
from kernellens.knowledge.search import KnowledgeBase, encoded


def evaluate(directory: Path, queries: Path) -> dict:
    knowledge = KnowledgeBase(directory)
    rows = []
    try:
        for case in json.loads(queries.read_text()):
            start = time.perf_counter()
            budget = case.get("max_chars", 12000)
            result = knowledge.search(
                case["query"],
                index=case.get("index", "auto"),
                top_k=case.get("top_k", 5),
                max_chars=budget,
                include_source=case.get("include_source", False),
            )
            elapsed = (time.perf_counter() - start) * 1000
            hits = result["results"][: case.get("rank", 5)]
            checks = {
                "route": result["intent"] == case["intent"],
                "budget": len(encoded(result)) <= budget,
                "bounded_candidates": all(
                    n <= 100 for n in result["candidate_counts"].values()
                ),
            }
            if "expected_name" in case:
                checks["relevance"] = any(
                    u["name"] == case["expected_name"] for u in hits
                )
            if "expected_path" in case:
                checks["relevance"] = any(
                    u["source_location"]["path"].startswith(case["expected_path"])
                    for u in hits
                )
            if "expected_status" in case:
                checks["status"] = result["status"] == case["expected_status"]
            if "missing_symbol" in case:
                checks["abstention"] = (
                    case["missing_symbol"] in result["missing_symbols"]
                    and not result["results"]
                )
            checks["family_precision"] = not any(
                u["source_location"]["path"].startswith(prefix)
                for u in result["results"]
                for prefix in case.get("forbidden_paths", [])
            )
            if case.get("require_complete_example"):
                checks["complete_example"] = any(
                    u["category"] == "example" and u.get("source_complete")
                    for u in result["results"]
                )
            if case.get("require_complete_api"):
                checks["complete_api"] = any(
                    u["category"] in {"api", "instruction"} and u.get("source_complete")
                    for u in result["results"]
                )
            rows.append(
                {
                    "id": case["id"],
                    "query": case["query"],
                    "passed": all(checks.values()),
                    "checks": checks,
                    "milliseconds": round(elapsed, 2),
                    "context_chars": result["context_chars"],
                    "indexes": result["indexes"],
                    "hits": [
                        {
                            "id": u["id"],
                            "name": u["name"],
                            "source_location": u["source_location"],
                        }
                        for u in result["results"]
                    ],
                }
            )
        return {
            "source_revision": knowledge.manifest["source_revision"],
            "passed": sum(r["passed"] for r in rows),
            "total": len(rows),
            "scope": "Curated retrieval regression, not a universal relevance guarantee or GPU validation",
            "results": rows,
        }
    finally:
        knowledge.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=Path, default=bundled_knowledge_dir())
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "knowledge/evaluation_queries.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.knowledge, args.queries)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "total": report["total"],
                "failed": [r for r in report["results"] if not r["passed"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
