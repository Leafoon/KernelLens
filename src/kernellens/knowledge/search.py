"""Selected-index retrieval and a hard character budget on serialized context."""

import json
import re
import sqlite3
from pathlib import Path

from kernellens.knowledge.schema import INDEXES, SCHEMA_VERSION, KnowledgeUnit, sha256
from kernellens.knowledge.terms import families, route, tokens


class KnowledgeError(ValueError):
    pass


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class KnowledgeBase:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        try:
            self.manifest = json.loads((self.directory / "manifest.json").read_text())
            if self.manifest.get("schema_version") != SCHEMA_VERSION:
                raise KnowledgeError(
                    "Knowledge schema mismatch; rebuild the knowledge base"
                )
            self.delivery_mode = self.manifest.get("delivery_mode", "source")
            if self.delivery_mode not in {"source", "snapshot"}:
                raise KnowledgeError("Unknown knowledge delivery mode")
            if (
                self.delivery_mode == "source"
                and self.manifest.get("repo_relative") != ".."
            ):
                raise KnowledgeError("Invalid repository-relative knowledge path")
            self.repo = (
                self.directory.parent if self.delivery_mode == "source" else None
            )
            index = self.directory / "index.sqlite3"
            if (
                index.is_symlink()
                or sha256(index.read_bytes())
                != self.manifest["delivery_hashes"]["index.sqlite3"]
            ):
                raise KnowledgeError("Knowledge index hash mismatch; rebuild")
            self.db = sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("PRAGMA trusted_schema=OFF")
            version = self.db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if version != (str(SCHEMA_VERSION),):
                raise KnowledgeError("Index schema mismatch")
        except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error) as exc:
            raise KnowledgeError(f"Cannot load knowledge delivery: {exc}") from exc

    def close(self):
        self.db.close()

    @property
    def source_root(self) -> str:
        return (
            str(self.repo) if self.repo else self.manifest.get("source_repository", "")
        )

    def _record(self, uid: str) -> KnowledgeUnit:
        row = self.db.execute("SELECT record FROM units WHERE id=?", (uid,)).fetchone()
        if not row:
            raise KnowledgeError(f"Unknown knowledge unit: {uid}")
        return KnowledgeUnit.model_validate_json(row[0])

    def _unit(self, uid: str) -> KnowledgeUnit:
        unit = self._record(uid)
        self._fresh(unit)
        return unit

    def _fresh(self, unit):
        if self.delivery_mode == "snapshot":
            # The source hash is provenance, not a claim about a local checkout.
            # The index that contains this record was hash-checked on loading.
            if (
                self.manifest["source_files"].get(unit.source_location.path)
                != unit.source_hash
            ):
                raise KnowledgeError(f"Snapshot source metadata mismatch: {unit.id}")
            return
        paths = [
            unit.source_location.path,
            *(p for p in unit.dependencies if p in self.manifest["source_files"]),
        ]
        for name in paths:
            path = self.repo / name
            if not path.resolve().is_relative_to(self.repo) or path.is_symlink():
                raise KnowledgeError(f"Unsafe knowledge source: {name}")
            try:
                actual = sha256(path.read_bytes())
            except OSError as exc:
                raise KnowledgeError(
                    f"Knowledge source missing: {name}; rebuild"
                ) from exc
            expected = self.manifest["source_files"].get(name)
            if (
                actual != expected
                or name == unit.source_location.path
                and actual != unit.source_hash
            ):
                raise KnowledgeError(
                    f"Stale knowledge source: {name}; rebuild before using it"
                )

    @staticmethod
    def _summary(unit):
        return {
            "id": unit.id,
            "category": unit.category,
            "name": unit.name,
            "aliases": unit.aliases,
            "visibility": unit.visibility,
            "targets": unit.targets,
            "description": unit.description[:800],
            "signature": unit.signature[:1800],
            "source_location": unit.source_location.model_dump(),
            "source_hash": unit.source_hash,
            "source_revision": unit.source_revision,
            "evidence_quality": unit.evidence_quality,
            "related_concepts": unit.related_concepts[:12],
            "cautions": unit.cautions,
        }

    def search(
        self,
        query: str,
        index: str = "auto",
        top_k: int = 5,
        max_chars: int = 10000,
        target: str = "",
        include_source: bool = False,
    ) -> dict:
        if not query.strip() or len(query) > 20000:
            raise KnowledgeError("Knowledge query must contain 1..20000 characters")
        if index != "auto" and index not in INDEXES:
            raise KnowledgeError("Unknown knowledge index")
        if not 1 <= top_k <= 10 or not 1500 <= max_chars <= 20000:
            raise KnowledgeError("top_k must be 1..10 and max_chars 1500..20000")
        if target not in {"", "cuda", "hip", "metal", "cpu", "webgpu"}:
            raise KnowledgeError("Unknown target filter")
        intent, selected, symbols = route(query)
        if intent == "concept":
            for word in re.findall(r"[A-Z][A-Za-z0-9_]+", query):
                known = self.db.execute(
                    "SELECT id FROM aliases WHERE alias=?", (word.casefold(),)
                ).fetchall()
                if known and all(
                    self._record(row[0]).category == "compiler" for row in known
                ):
                    intent, selected = "compiler", ["compiler", "api", "concept"]
                    break
        if index != "auto":
            selected = [index]
        exact, missing = set(), []
        for symbol in symbols:
            hits = self.db.execute(
                "SELECT id FROM aliases WHERE alias=?", (symbol.casefold(),)
            ).fetchall()
            if hits:
                exact.update(row[0] for row in hits)
            else:
                missing.append(symbol)
        if intent == "compiler":
            for word in re.findall(r"\b[A-Za-z_]\w*\b", query):
                exact.update(
                    row[0]
                    for row in self.db.execute(
                        "SELECT id FROM aliases WHERE alias=?", (word.casefold(),)
                    )
                )
        scores, candidates = {uid: 1000.0 for uid in exact}, {}
        terms = tokens(query)[:32]
        if terms and not (intent == "api" and symbols and not exact):
            match = " OR ".join('"' + word.replace('"', '""') + '"' for word in terms)
            for priority, selected_index in enumerate(selected):
                table = selected_index + "_index"
                rows = self.db.execute(
                    f"SELECT id, bm25({table}, 0, 8, 4, 2, 0.3) FROM {table} WHERE {table} MATCH ? ORDER BY 2, id LIMIT 100",
                    (match,),
                ).fetchall()
                candidates[selected_index] = len(rows)
                for rank, (uid, _) in enumerate(rows):
                    scores[uid] = max(
                        scores.get(uid, 0), (1.0 - 0.12 * priority) / (10 + rank)
                    )
        requested_families = families(" ".join(terms))
        # Choose the operator family, not an incidental primitive (attention uses
        # both GEMM and reductions). A GEMM request must not surface MLA scores.
        primary = next(
            (
                f
                for f in (
                    "attention",
                    "convolution",
                    "gemm",
                    "reduction",
                    "layout",
                    "pipeline",
                    "elementwise",
                )
                if f in requested_families
            ),
            None,
        )
        records = {}
        for uid in list(scores):
            unit = self._record(uid)
            if (
                not set(unit.indexes).intersection(selected)
                or target
                and unit.targets
                and target not in unit.targets
            ):
                del scores[uid]
                continue
            if uid not in exact:
                if (
                    intent in {"operator", "example"}
                    and primary
                    and primary
                    not in families(unit.source_location.path + " " + unit.name)
                ):
                    del scores[uid]
                    continue
                if (
                    intent == "api"
                    and symbols
                    and not any(
                        s in unit.symbols
                        or s.rsplit(".", 1)[-1] == unit.name.rsplit(".", 1)[-1]
                        for s in symbols
                    )
                ):
                    del scores[uid]
                    continue
                name_terms = set(tokens(unit.name + " " + " ".join(unit.aliases)))
                coverage = len(name_terms.intersection(terms)) / max(
                    1, len([t for t in terms if t.isascii()])
                )
                scores[uid] += min(0.12, 0.12 * coverage)
                if intent in {"concept", "target"} and unit.category == "concept":
                    scores[uid] += 0.13
                if intent in {"operator", "example"} and unit.category == "example":
                    scores[uid] += 0.06
                    starter = {
                        "gemm": "examples/gemm/",
                        "attention": "examples/flash_attention/",
                        "reduction": "examples/online_softmax/",
                    }.get(primary, "")
                    if starter and unit.source_location.path.startswith(starter):
                        scores[uid] += 0.08
                        if (
                            primary == "gemm"
                            and unit.source_location.path
                            == "examples/gemm/example_gemm.py"
                        ):
                            scores[uid] += 0.12
                    if (
                        "fwd" in terms
                        and "bwd" not in terms
                        and "bwd" in unit.source_location.path
                    ) or (
                        "bwd" in terms
                        and "fwd" not in terms
                        and "fwd" in unit.source_location.path
                    ):
                        scores[uid] *= 0.6
                if intent in {"operator", "example"}:
                    path = unit.source_location.path.lower()
                    for feature, clues in {
                        "autotune": ("autotun",),
                        "sparse": ("sparse", "gemm_sp/"),
                        "splitk": ("splitk", "split_k"),
                        "persistent": ("persistent",),
                        "grouped": ("grouped",),
                        "fp8": ("fp8",),
                        "dequant": ("dequant",),
                    }.items():
                        if any(clue in path for clue in clues) and not any(
                            clue in query.lower() or clue in terms
                            for clue in (feature, *clues)
                        ):
                            scores[uid] *= 0.25
                if unit.visibility == "public" and unit.category in {
                    "api",
                    "instruction",
                }:
                    scores[uid] += 0.04
                if (
                    intent in {"operator", "example"}
                    and not re.search(
                        r"benchmark|performance|性能|测量|基准", query, re.I
                    )
                    and re.search(r"benchmark|performance|evaluation", unit.name, re.I)
                ):
                    scores[uid] *= 0.1
                if not re.search(
                    r"sm\d|blackwell|hopper|tcgen|wgmma", query, re.I
                ) and re.search(r"sm\d|tcgen|wgmma", unit.source_location.path, re.I):
                    scores[uid] *= 0.6
            elif unit.signature.startswith("module "):
                scores[uid] += 2 if re.search(r"模块|module", query, re.I) else 0
            else:
                scores[uid] += 1
            records[uid] = unit
        response = {
            "status": "ok",
            "intent": intent,
            "indexes": selected,
            "candidate_counts": candidates,
            "missing_symbols": missing,
            "source_revision": self.manifest["source_revision"],
            "source_root": self.source_root,
            "delivery_mode": self.delivery_mode,
            "results": [],
            "stale_sources": [],
            "omitted_for_budget": [],
            "truncated": False,
            "context_chars": 0,
        }
        category_counts = {}
        ranked = sorted(scores, key=lambda item: (-scores[item], item))
        if include_source and intent == "operator" and top_k >= 2:
            # A complete example and a relevant callable are the generation
            # prerequisites. Reserve their context before ancillary summaries.
            required = []
            for categories in ({"example"}, {"api", "instruction"}):
                best = next(
                    (uid for uid in ranked if records[uid].category in categories), None
                )
                if best:
                    required.append(best)
            ranked = required + [uid for uid in ranked if uid not in required]
        for uid in ranked:
            try:
                unit = records[uid]
                self._fresh(unit)
            except KnowledgeError as exc:
                if len(response["stale_sources"]) < 5:
                    response["stale_sources"].append(str(exc))
                else:
                    response["truncated"] = True
                continue
            if target and unit.targets and target not in unit.targets:
                continue
            if not set(unit.indexes).intersection(selected):
                continue
            if (
                intent in {"operator", "example"}
                and top_k >= 3
                and category_counts.get(unit.category, 0)
                >= (1 if include_source else 2)
            ):
                continue
            result = self._summary(unit)
            result["match"] = "exact_symbol" if uid in exact else "lexical"
            result["excerpt"] = unit.content[:1200]
            result["excerpt_truncated"] = len(unit.content) > 1200
            result["source_complete"] = False
            if include_source and len(unit.content) + len(unit.context) <= 4000:
                result["excerpt"] = unit.content
                result["excerpt_truncated"] = False
                result["source_complete"] = True
                result["context"] = unit.context
                result["dependencies"] = [
                    d
                    for d in unit.dependencies
                    if d not in self.manifest["source_files"]
                ]
            result["examples"] = unit.examples[:2]
            result["score"] = round(scores[uid], 6)
            candidate = {**response, "results": [*response["results"], result]}
            if len(encoded(candidate)) > max_chars - 150:
                result.pop("examples")
                result["excerpt"] = unit.content[:300]
                result["excerpt_truncated"] = len(unit.content) > 300
                result["source_complete"] = (
                    len(unit.content) <= 300 and not unit.context
                )
                result.pop("context", None)
                result.pop("dependencies", None)
                candidate = {**response, "results": [*response["results"], result]}
            if len(encoded(candidate)) > max_chars - 150:
                response["truncated"] = True
                if len(response["omitted_for_budget"]) < 3:
                    response["omitted_for_budget"].append(uid)
                continue
            response["results"].append(result)
            category_counts[unit.category] = category_counts.get(unit.category, 0) + 1
            if len(response["results"]) >= top_k:
                break
        if not response["results"]:
            response["status"] = (
                "stale"
                if response["stale_sources"]
                else "budget_limited"
                if response["omitted_for_budget"]
                else "no_match"
            )
        # Error metadata is bounded too; the DB/whole repository never enters context.
        while len(encoded(response)) > max_chars - 100 and response["stale_sources"]:
            response["stale_sources"].pop()
            response["truncated"] = True
        return self._finish(response, max_chars)

    @staticmethod
    def _finish(response, max_chars):
        for _ in range(3):
            response["context_chars"] = len(encoded(response))
        if len(encoded(response)) > max_chars:
            raise KnowledgeError(
                "Knowledge metadata exceeds the requested context budget"
            )
        return response

    def read(self, unit_id: str, start_line: int = 0, max_chars: int = 10000) -> dict:
        if not 1500 <= max_chars <= 20000:
            raise KnowledgeError("max_chars must be 1500..20000")
        unit = self._unit(unit_id)
        location = unit.source_location
        start_line = start_line or location.start_line
        if not location.start_line <= start_line <= location.end_line:
            raise KnowledgeError("start_line must be inside the semantic unit")
        result = self._summary(unit)
        result["source_root"] = self.source_root
        result["delivery_mode"] = self.delivery_mode
        result.update(
            {
                "context": unit.context,
                "parameters": unit.parameters,
                "returns": unit.returns,
                "dependencies": [
                    d
                    for d in unit.dependencies
                    if d not in self.manifest["source_files"]
                ],
                "export_source_files_checked": sum(
                    d in self.manifest["source_files"] for d in unit.dependencies
                )
                if self.repo
                else 0,
                "examples": unit.examples[:3],
                "content": "",
                "start_line": start_line,
                "next_line": None,
                "truncated": False,
                "context_chars": 0,
            }
        )
        # Source definitions remain whole in storage. Pagination affects only transfer.
        while len(encoded(result)) > max_chars // 2:
            if result.get("examples"):
                result["examples"].pop()
            elif result.get("context"):
                result["context"] = result["context"][: len(result["context"]) // 2]
                result["context_truncated"] = True
            elif result.get("parameters"):
                result["parameters"] = []
                result["parameters_in_source"] = True
            else:
                break
        lines = unit.content.splitlines()
        offset = start_line - location.start_line
        for i in range(offset, len(lines)):
            line = lines[i] + "\n"
            if (
                len(encoded(result | {"content": result["content"] + line}))
                > max_chars - 150
            ):
                result["truncated"], result["next_line"] = True, location.start_line + i
                break
            result["content"] += line
        if not result["content"]:
            raise KnowledgeError(
                "A source line or its metadata exceeds this budget; increase max_chars or inspect the source location"
            )
        return self._finish(result, max_chars)

    def validate(self) -> dict:
        errors = []
        for name, expected in self.manifest["delivery_hashes"].items():
            file = self.directory / name
            if (
                not file.resolve().is_relative_to(self.directory)
                or file.is_symlink()
                or not file.is_file()
                or sha256(file.read_bytes()) != expected
            ):
                errors.append("Delivery mismatch: " + name)
        for path, expected in (
            self.manifest["source_files"].items() if self.repo else ()
        ):
            file = self.repo / path
            if (
                not file.resolve().is_relative_to(self.repo)
                or file.is_symlink()
                or not file.is_file()
                or sha256(file.read_bytes()) != expected
            ):
                errors.append("Source mismatch: " + path)
        count = 0
        for row in self.db.execute("SELECT record FROM units"):
            unit = KnowledgeUnit.model_validate_json(row[0])
            content = (
                "\n".join(
                    (self.repo / unit.source_location.path)
                    .read_text()
                    .splitlines()[
                        unit.source_location.start_line
                        - 1 : unit.source_location.end_line
                    ]
                )
                if self.repo and not errors
                else None
            )
            if content is not None and content != unit.content:
                errors.append("Source range mismatch: " + unit.id)
            if (
                self.manifest["source_files"].get(unit.source_location.path)
                != unit.source_hash
            ):
                errors.append("Source metadata mismatch: " + unit.id)
            if (
                len(unit.content.split("\n"))
                != unit.source_location.end_line - unit.source_location.start_line + 1
            ):
                errors.append("Stored line range mismatch: " + unit.id)
            count += 1
        return {
            "status": "failed" if errors else "passed",
            "delivery_mode": self.delivery_mode,
            "local_source_checked": self.repo is not None,
            "unit_count": count,
            "errors": errors,
            "indexes": self.manifest["indexes"],
            "limitations": self.manifest["limitations"],
        }
