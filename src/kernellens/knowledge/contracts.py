"""Limited call-shape checks against retrieved source signatures, never execution."""

import ast

from kernellens.knowledge.search import KnowledgeBase, KnowledgeError


def check_calls(source: str, knowledge: KnowledgeBase) -> dict:
    tree = ast.parse(source)
    bindings = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("tilelang"):
                    bindings[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else "tilelang"
                    )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("tilelang")
        ):
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = (
                        node.module + "." + alias.name
                    )
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        value = ast.unparse(node.func)
        root, _, tail = value.partition(".")
        if root not in bindings:
            continue
        symbol = bindings[root] + ("." + tail if tail else "")
        if symbol.startswith("tilelang.language."):
            symbol = "T." + symbol.removeprefix("tilelang.language.")
        entry = {
            "symbol": symbol,
            "line": node.lineno,
            "status": "inconclusive",
            "issues": [],
        }
        exported = knowledge.manifest.get("public_exports", {})
        ids = knowledge.db.execute(
            "SELECT id FROM aliases WHERE alias=?", (symbol.casefold(),)
        ).fetchall()
        if not ids or symbol not in exported:
            entry["issues"].append(
                "No confirmed public export/signature in this delivery; retrieve source evidence before adopting this call."
            )
            calls.append(entry)
            continue
        try:
            candidates = [knowledge._unit(row[0]) for row in ids]
            unit = next(
                (
                    u
                    for u in candidates
                    if symbol in u.aliases and not u.signature.startswith("module ")
                ),
                candidates[0],
            )
        except KnowledgeError as exc:
            entry["issues"].append(str(exc))
            calls.append(entry)
            continue
        entry.update(
            unit_id=unit.id,
            source_location=unit.source_location.model_dump(),
            signature=unit.signature,
        )
        if not unit.parameters and not unit.signature.startswith(
            symbol.rsplit(".", 1)[-1] + "("
        ):
            entry["issues"].append(
                "Export exists but callable contract was not extracted."
            )
        else:
            params = unit.parameters
            names = {p["name"] for p in params if p["kind"] != "positional_only"}
            kwargs = any(p["kind"] == "var_keyword" for p in params)
            invalid = [
                k.arg
                for k in node.keywords
                if k.arg and k.arg not in names and not kwargs
            ]
            if invalid:
                entry["status"] = "failed"
                entry["issues"].append("Unexpected keyword(s): " + ", ".join(invalid))
            elif any(k.arg is None for k in node.keywords) or any(
                isinstance(a, ast.Starred) for a in node.args
            ):
                entry["issues"].append(
                    "Dynamic *args/**kwargs cannot be checked statically."
                )
            else:
                entry["status"] = "passed"
        calls.append(entry)
    status = (
        "failed"
        if any(c["status"] == "failed" for c in calls)
        else "inconclusive"
        if any(c["status"] != "passed" for c in calls)
        else "passed"
        if calls
        else "not_applicable"
    )
    return {
        "status": status,
        "scope": "public export and keyword names only; no type, shape, lowering or runtime proof",
        "calls": calls,
        "gpu_validation": "not_run",
    }
