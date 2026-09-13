"""Reproducible local knowledge delivery and independent FTS indexes."""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from kernellens.knowledge.extract import Extractor
from kernellens.knowledge.schema import INDEXES, SCHEMA_VERSION, sha256
from kernellens.knowledge.terms import families, tokens

CAPABILITY_IDS = {
    "gemm": "gemm_like_patterns",
    "attention": "attention_like_patterns",
    "reduction": "reductions",
    "layout": "tiling_and_schedule",
    "pipeline": "pipelining",
    "convolution": "convolution_like_patterns",
    "elementwise": "elementwise_and_fusion_patterns",
}


def dump(path: Path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_index(path: Path, units):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE units (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("CREATE TABLE aliases (alias TEXT, id TEXT, PRIMARY KEY(alias,id))")
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        db.execute(
            "INSERT INTO metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        for index in INDEXES:
            db.execute(
                f"CREATE VIRTUAL TABLE {index}_index USING fts5(id UNINDEXED, name, keywords, description, detail)"
            )
        for unit in units:
            record = unit.model_dump()
            db.execute(
                "INSERT INTO units VALUES (?, ?)",
                (unit.id, json.dumps(record, ensure_ascii=False)),
            )
            for alias in {unit.name, *unit.aliases}:
                db.execute(
                    "INSERT OR IGNORE INTO aliases VALUES (?, ?)",
                    (alias.casefold(), unit.id),
                )
            if unit.category == "compiler":
                # A pass name in an error usually has no Python module prefix.
                alias = unit.name.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
                db.execute(
                    "INSERT OR IGNORE INTO aliases VALUES (?, ?)",
                    (alias.casefold(), unit.id),
                )
            for index in unit.indexes:
                fields = [
                    unit.name + " " + " ".join(unit.aliases),
                    " ".join(unit.keywords),
                    unit.description + " " + unit.when_to_use,
                    unit.signature + " " + unit.content,
                ]
                db.execute(
                    f"INSERT INTO {index}_index VALUES (?, ?, ?, ?, ?)",
                    (unit.id, *(" ".join(tokens(f)) for f in fields)),
                )


def compatibility(out: Path, units, manifest):
    """MCP views derived from the same units, not a separately curated truth."""
    examples = [u for u in units if u.category == "example"]
    patterns, usages = [], []
    for unit in examples:
        group = families(unit.source_location.path)
        evidence = [
            unit.source_location.model_dump()
            | {
                "sha256": unit.source_hash,
                "revision": unit.source_revision,
                "unit_id": unit.id,
            }
        ]
        patterns.append(
            {
                "pattern_id": unit.id,
                "pattern_name": unit.name,
                "category": "operator",
                "task_family": group,
                "summary": unit.description,
                "required_symbols": unit.symbols,
                "control_flow_shape": unit.operator_structure.get("control_flow", []),
                "memory_flow_shape": {
                    key: unit.operator_structure.get(key, [])
                    for key in (
                        "allocations",
                        "transfers",
                        "compute",
                        "synchronization",
                    )
                },
                "device_strategy": {
                    "source_targets": unit.targets,
                    "architecture": "unknown",
                    "notes": unit.cautions,
                },
                "reuse_guidance": unit.cautions,
                "related_usage_patterns": ["U" + unit.id],
                "related_capabilities": [CAPABILITY_IDS[f] for f in group],
                "confidence": 0.65,
                "evidence": evidence,
            }
        )
        usages.append(
            {
                "usage_id": "U" + unit.id,
                "scenario": unit.name,
                "goal": unit.description,
                "ordered_steps": [
                    "Read the complete source constructor and its imports/constants.",
                    "Resolve referenced helpers and confirm public API signatures.",
                    "Adapt workload/target and validate on matching hardware; no execution is claimed by this record.",
                ],
                "symbols_used": unit.symbols,
                "source_files": [unit.source_location.path],
                "prerequisites": unit.dependencies,
                "failure_modes": unit.cautions,
                "device_execution_notes": {
                    "targets": unit.targets,
                    "gpu_validation": "not_run",
                },
                "pattern_id": unit.id,
                "confidence": 0.65,
                "evidence": evidence,
            }
        )
    capabilities = []
    for family in sorted(
        {f for u in examples for f in families(u.source_location.path)}
    ):
        selected = [u for u in examples if family in families(u.source_location.path)]
        capabilities.append(
            {
                "capability_id": CAPABILITY_IDS[family],
                "summary": f"{family} source patterns in the current TileLang checkout.",
                "primary_symbols": sorted({s for u in selected for s in u.symbols}),
                "related_patterns": [u.id for u in selected],
                "when_to_use": f"Find {family} operator examples before generating or optimizing.",
                "device_adaptation": "Use source target and explicit API constraints; architecture unknown unless source confirms it.",
                "confidence": 0.65,
                "evidence": [u.source_location.model_dump() for u in selected],
            }
        )
    dump(out / "capability_map.json", {"capabilities": capabilities})
    jsonl(out / "patterns.jsonl", patterns)
    jsonl(out / "usage_patterns.jsonl", usages)
    jsonl(
        out / "apis.jsonl",
        (
            {
                "qualified_name": alias,
                "symbol_type": "source_declaration",
                "signature": u.signature,
                "visibility": u.visibility,
                "module": u.name.rpartition(".")[0],
                "file_path": u.source_location.path,
                "line_start": u.source_location.start_line,
                "line_end": u.source_location.end_line,
                "operator_relevance": u.related_concepts,
                "short_summary": u.description,
                "docstring": u.description,
                "unit_id": u.id,
                "evidence": [
                    u.source_location.model_dump()
                    | {"sha256": u.source_hash, "revision": u.source_revision}
                ],
            }
            for u in units
            if "api" in u.indexes
            for alias in [u.name, *u.aliases]
        ),
    )
    jsonl(
        out / "source_chunks.jsonl",
        (
            {
                "chunk_id": u.id,
                "file_path": u.source_location.path,
                "start_line": u.source_location.start_line,
                "end_line": u.source_location.end_line,
                "summary": u.description,
                "why_it_matters": u.when_to_use,
                "symbols": [u.name, *u.aliases, *u.symbols],
                "source": u.content,
                "device_notes": u.cautions,
                "related_capabilities": [
                    CAPABILITY_IDS[f] for f in families(u.source_location.path)
                ],
                "related_patterns": [u.id] if u.category == "example" else [],
                "sha256": u.source_hash,
                "revision": u.source_revision,
            }
            for u in units
        ),
    )
    ids = {u.id for u in units}
    nodes = [
        {
            "id": u.id,
            "type": u.category,
            "name": u.name,
            "label": u.name,
            "attrs": {"source_location": u.source_location.model_dump()},
        }
        for u in units
    ]
    edges = [
        {
            "source": u.id,
            "target": related,
            "type": "references",
            "edge_type": "references",
        }
        for u in units
        for related in u.related_concepts
        if related in ids
    ]
    dump(out / "semantic_graph.json", {"nodes": nodes, "edges": edges})
    # The diagram shows the graph schema; the JSON carries the full graph.
    (out / "semantic_graph.mmd").write_text(
        "graph LR\n  Operator --> Example\n  Example --> API\n  Concept --> API\n  API --> Source\n  Compiler --> Source\n",
        encoding="utf-8",
    )
    (out / "retrieval_plan.md").write_text(
        "# Retrieval plan\n\nValidate manifest and sources first.\n\n"
        "MCP layers: capability_map → patterns → usage_patterns → apis → source_chunks → semantic_graph; original source only when evidence is missing.\n\n"
        "KernelLens routing: API question → API; DSL → Concept/API; kernel generation → Operator/Example/API; compiler error → Compiler/API; target → Concept/Compiler.\n\n"
        "Use Top-K ≤ 10, context ≤ 20000 characters. Preserve provenance, unknown targets, missing evidence and truncation flags. Never claim runtime validation from these records.\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        "# TileLang structured knowledge\n\n"
        f"Source revision: `{manifest['source_revision']}`; VERSION: `{manifest['source_version']}`.\n\n"
        "Generated by KernelLens. Rebuild with `python -m kernellens.knowledge build --repo /path/to/tilelang`.\n\n"
        "`units.jsonl` is the semantic source of all views. `index.sqlite3` contains five FTS5 indexes. Each record includes source lines, hash and revision. `manifest.json` records extraction coverage and limitations.\n\n"
        "Examples are source references, not verified independent programs. C++ extraction is structural and intentionally incomplete. No TileLang code was executed.\n\n"
        "Source snippets retain the TileLang repository license; see the source repository LICENSE.\n",
        encoding="utf-8",
    )


def build(repo: Path) -> dict:
    repo = repo.resolve()
    for marker in ("tilelang/__init__.py", "tilelang/language/__init__.py", "VERSION"):
        if not (repo / marker).is_file():
            raise ValueError(f"Not a TileLang checkout; missing {marker}")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    extractor = Extractor(repo, revision)
    units = extractor.run()
    if not units or any(
        not any(index in u.indexes for u in units) for index in INDEXES
    ):
        raise ValueError("Extraction did not populate all five indexes")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": "kernellens.knowledge",
        "repo_name": "TileLang",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source_roots": [
            "tilelang",
            "docs/programming_guides",
            "docs/get_started",
            "docs/compiler_internals",
            "docs/deeplearning_operators",
            "docs/tutorials",
            "docs/tools",
            "docs/runtime_internals",
            "examples",
            "src",
        ],
        "total_python_files": sum(p.endswith(".py") for p in extractor.hashes),
        "device_integration": {
            "targets": sorted({t for u in units for t in u.targets}),
            "architecture_inference": False,
            "gpu_validation": "not_run",
        },
        "source_revision": revision,
        "source_version": (repo / "VERSION").read_text().strip(),
        "repo_relative": "..",
        "counts": dict(Counter(u.category for u in units)),
        "indexes": {index: sum(index in u.indexes for u in units) for index in INDEXES},
        "source_files": extractor.hashes,
        "public_exports": extractor.public_exports,
        "diagnostics": extractor.diagnostics,
        "excluded": [
            "3rdparty",
            "testing",
            "images",
            "benchmark",
            "build artifacts",
            "unselected documentation",
            "test/regression/benchmark example scripts",
        ],
        "limitations": [
            "C++ conservative declaration scanner, not a full compiler parser.",
            "External/dynamic exports may have no extracted definition; diagnostics list them.",
            "Targets are source dialect provenance; no inferred minimum architecture.",
            "No GPU compilation, numerical or performance validation.",
        ],
    }
    destination = repo / "tilelang_knowledge"
    if destination.is_symlink():
        raise ValueError("Knowledge output must not be a symlink")
    if destination.exists():
        old_manifest = json.loads((destination / "manifest.json").read_text())
        if old_manifest.get("generator") != "kernellens.knowledge":
            raise ValueError(
                "Refusing to replace a knowledge delivery owned by another generator"
            )
    temp = Path(tempfile.mkdtemp(prefix=".tilelang-knowledge-build-", dir=repo))
    backup = None
    try:
        jsonl(temp / "units.jsonl", (u.model_dump() for u in units))
        make_index(temp / "index.sqlite3", units)
        compatibility(temp, units, manifest)
        manifest["delivery_hashes"] = {
            f.name: sha256(f.read_bytes())
            for f in sorted(temp.iterdir())
            if f.is_file()
        }
        dump(temp / "manifest.json", manifest)
        if destination.exists():
            backup = temp.with_name(temp.name + "-previous")
            os.replace(destination, backup)
        try:
            os.replace(temp, destination)
        except OSError:
            if backup:
                os.replace(backup, destination)
                backup = None
            raise
        if backup:
            shutil.rmtree(backup)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return {
        "path": str(destination),
        "source_revision": revision,
        "counts": manifest["counts"],
        "indexes": manifest["indexes"],
        "source_files": len(extractor.hashes),
        "diagnostics": len(extractor.diagnostics),
    }
