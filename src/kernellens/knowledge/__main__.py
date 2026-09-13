"""Offline build, validation and retrieval CLI; no credentials required."""

import argparse
import json
from pathlib import Path

from kernellens.knowledge import bundled_knowledge_dir
from kernellens.knowledge.build import build
from kernellens.knowledge.bundle import export_bundle
from kernellens.knowledge.search import KnowledgeBase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    create.add_argument("--repo", type=Path, required=True)
    bundle = sub.add_parser("bundle", help="维护者：导出无需源码的随包知识")
    bundle.add_argument("--knowledge", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    for name in ("search", "read", "validate"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--knowledge", type=Path, default=bundled_knowledge_dir())
        if name == "search":
            cmd.add_argument("query")
            cmd.add_argument("--index", default="auto")
            cmd.add_argument("--top-k", type=int, default=5)
            cmd.add_argument("--target", default="")
            cmd.add_argument("--include-source", action="store_true")
        if name == "read":
            cmd.add_argument("unit_id")
            cmd.add_argument("--start-line", type=int, default=0)
        if name in {"search", "read"}:
            cmd.add_argument("--max-chars", type=int, default=10000)
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.repo)
    elif args.command == "bundle":
        result = export_bundle(args.knowledge, args.output)
    else:
        kb = KnowledgeBase(args.knowledge)
        try:
            if args.command == "search":
                result = kb.search(
                    args.query,
                    args.index,
                    args.top_k,
                    args.max_chars,
                    args.target,
                    args.include_source,
                )
            elif args.command == "read":
                result = kb.read(args.unit_id, args.start_line, args.max_chars)
            else:
                result = kb.validate()
        finally:
            kb.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
