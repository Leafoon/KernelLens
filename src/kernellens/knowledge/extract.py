"""Semantic extraction without importing or executing repository code."""

import ast
import re
from collections import defaultdict
from pathlib import Path

from kernellens.knowledge.schema import KnowledgeUnit, SourceLocation, sha256, unit_id
from kernellens.knowledge.terms import families, targets


def module_name(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def statements(body):
    """Conditional top-level imports are inspected, never executed."""
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            for attr in ("body", "orelse", "finalbody"):
                yield from statements(getattr(node, attr, []))
            for handler in getattr(node, "handlers", []):
                yield from statements(handler.body)


class PythonSurface:
    def __init__(self, sources: dict[str, str], diagnostics: list[str]):
        self.modules = {}
        self.cache = {}
        self.previous = {}
        self.visited = set()
        self.diagnostics = diagnostics
        for path, text in sources.items():
            try:
                self.modules[module_name(path)] = (path, ast.parse(text))
            except SyntaxError as exc:
                diagnostics.append(
                    f"Python parse skipped: {path}:{exc.lineno}: {exc.msg}"
                )

    def exports(self, module: str, stack: tuple = ()) -> tuple[dict, dict]:
        if module in self.cache:
            return self.cache[module]
        if module in stack:
            return self.previous.get(module, ({}, {}))
        if module not in self.modules:
            return {}, {}
        self.visited.add(module)
        path, tree = self.modules[module]
        bindings, values = {}, {}

        def literal(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return values.get(node.id)
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                result = []
                for item in node.elts:
                    value = literal(
                        item.value if isinstance(item, ast.Starred) else item
                    )
                    if isinstance(item, ast.Starred):
                        result.extend(value if isinstance(value, (list, tuple)) else [])
                    elif isinstance(value, str):
                        result.append(value)
                return result
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left, right = literal(node.left), literal(node.right)
                return (
                    left + right
                    if isinstance(left, list) and isinstance(right, list)
                    else None
                )
            if (
                isinstance(node, ast.Call)
                and node.args
                and ast.unparse(node.func) in {"tuple", "list", "set", "dict.fromkeys"}
            ):
                return literal(node.args[0])
            return None

        for node in statements(tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings[node.name] = module + "." + node.name
            elif isinstance(node, ast.ImportFrom):
                package = (
                    module
                    if path.endswith("/__init__.py")
                    else module.rpartition(".")[0]
                )
                if node.level:
                    parts = package.split(".")[
                        : len(package.split(".")) - node.level + 1
                    ]
                    imported = ".".join(parts + ([node.module] if node.module else []))
                else:
                    imported = node.module or ""
                exports, imported_values = self.exports(imported, (*stack, module))
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.name == "*":
                        bindings.update(exports)
                    else:
                        bindings[local] = exports.get(
                            alias.name, imported + "." + alias.name
                        )
                        if alias.name in imported_values:
                            values[local] = imported_values[alias.name]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                assigned = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for item in assigned:
                    if isinstance(item, ast.Name):
                        values[item.id] = literal(node.value)
                        bindings[item.id] = (
                            bindings.get(node.value.id, module + "." + item.id)
                            if isinstance(node.value, ast.Name)
                            else module + "." + item.id
                        )
        names = values.get("__all__")
        if isinstance(names, list):
            exports = {name: bindings[name] for name in names if name in bindings}
            missing = sorted(set(names) - bindings.keys())
            if missing:
                self.diagnostics.append(
                    f"Unresolved static exports {module}: {', '.join(missing)}"
                )
        else:
            exports = {
                name: target
                for name, target in bindings.items()
                if not name.startswith("_")
            }
        self.cache[module] = exports, values
        return exports, values

    def resolve(self, facades):
        # Bounded fixed-point propagation handles facade cycles without either
        # caching an incomplete first traversal or exploring exponentially many paths.
        for _ in range(16):
            self.cache = {}
            for module in facades:
                self.exports(module)
            if self.cache == self.previous:
                return
            self.previous = self.cache
        raise ValueError("Static export graph did not converge after 16 rounds")


class Extractor:
    def __init__(self, root: Path, revision: str):
        self.root, self.revision = root, revision
        self.units: dict[str, KnowledgeUnit] = {}
        self.sources: dict[str, str] = {}
        self.hashes: dict[str, str] = {}
        self.diagnostics: list[str] = []
        self.public_exports: dict[str, str] = {}

    def read(self, path: Path) -> str:
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError(f"Unsafe source path: {path}")
        name = path.relative_to(self.root).as_posix()
        if name not in self.sources:
            data = path.read_bytes()
            self.sources[name] = data.decode("utf-8")
            self.hashes[name] = sha256(data)
        return self.sources[name]

    def add(
        self,
        path: str,
        start: int,
        end: int,
        *,
        category: str,
        name: str,
        indexes: list[str],
        description: str = "",
        **kwargs,
    ) -> KnowledgeUnit:
        content = "\n".join(self.sources[path].splitlines()[start - 1 : end])
        group = families(path + " " + name)
        uid = unit_id(category, path, kwargs.pop("identity", name))
        layer = "implementation" if category == "compiler" else "user"
        unit = KnowledgeUnit(
            id=uid,
            category=category,
            name=name,
            description=description,
            when_to_use=kwargs.pop(
                "when_to_use",
                description
                or f"Inspect {name} in {path}; usage is not separately documented.",
            ),
            indexes=indexes,
            layer=layer,
            visibility=kwargs.pop(
                "visibility", "internal" if layer == "implementation" else "module"
            ),
            source_location=SourceLocation(path=path, start_line=start, end_line=end),
            source_revision=self.revision,
            source_hash=self.hashes[path],
            content=content,
            evidence_quality=kwargs.pop("evidence_quality", "source"),
            keywords=kwargs.pop(
                "keywords", [*group, *path.replace("/", " ").replace("_", " ").split()]
            ),
            related_concepts=kwargs.pop("related_concepts", group),
            targets=kwargs.pop("targets", targets(path)),
            **kwargs,
        )
        self.units[uid] = unit
        return unit

    def python(self):
        paths = sorted((self.root / "tilelang").rglob("*.py"))
        source = {
            p.relative_to(self.root).as_posix(): self.read(p)
            for p in paths
            if not p.is_symlink()
        }
        surface = PythonSurface(source, self.diagnostics)
        aliases = defaultdict(list)
        facades = [
            "tilelang",
            "tilelang.language",
            "tilelang.layout",
            "tilelang.profiler",
            "tilelang.jit",
        ]
        facades += [
            f"tilelang.{backend}.language"
            for backend in ("cuda", "rocm", "cpu", "metal", "webgpu")
        ]
        surface.resolve(facades)
        for module in facades:
            for name, qualified in surface.exports(module)[0].items():
                alias = ("T" if module == "tilelang.language" else module) + "." + name
                aliases[qualified].append(alias)
                self.public_exports[alias] = qualified
        # Callable proxy exports (e.g. Tensor = TensorProxy()) get the signature
        # of their explicit __call__, while keeping the export files as evidence.
        for module, (_, tree) in surface.modules.items():
            classes = {
                n.name: n for n in statements(tree.body) if isinstance(n, ast.ClassDef)
            }
            for node in statements(tree.body):
                if (
                    not isinstance(node, (ast.Assign, ast.AnnAssign))
                    or not isinstance(node.value, ast.Call)
                    or not isinstance(node.value.func, ast.Name)
                ):
                    continue
                cls = classes.get(node.value.func.id)
                if cls is None or not any(
                    isinstance(n, ast.FunctionDef) and n.name == "__call__"
                    for n in cls.body
                ):
                    continue
                assigned = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in assigned:
                    if isinstance(target, ast.Name):
                        qualified = module + "." + target.id
                        if qualified in aliases:
                            aliases[module + "." + cls.name + ".__call__"].extend(
                                aliases.pop(qualified)
                            )
        facade_paths = sorted(surface.modules[m][0] for m in surface.visited)
        for module in facades:
            if module not in surface.modules:
                continue
            path, tree = surface.modules[module]
            first = tree.body[0]
            doc = ast.get_docstring(tree)
            self.add(
                path,
                1,
                first.end_lineno,
                category="api",
                name=module,
                indexes=["api"],
                description=doc
                or f"Python module {module}; exported names are resolved without executing imports.",
                signature="module " + module,
                visibility="module",
                dependencies=facade_paths,
                symbols=[
                    ("T" if module == "tilelang.language" else module) + "." + name
                    for name in surface.exports(module)[0]
                ],
                cautions=[
                    "Module overview; inspect individual API units for callable contracts."
                ],
            )
        for module, (path, tree) in surface.modules.items():
            compiler = (
                any(
                    f"/{part}/" in "/" + path
                    for part in ("engine", "transform", "backend", "tileop", "parser")
                )
                or "/jit/adapter/" in path
            )
            public_area = (
                any(
                    f"/{part}/" in "/" + path
                    for part in ("language", "layout", "jit", "profiler")
                )
                or path == "tilelang/__init__.py"
                or any(qualified.rpartition(".")[0] == module for qualified in aliases)
            )
            if not compiler and not public_area:
                continue
            definitions = {}
            for node in statements(tree.body):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    definitions[node.name] = (
                        node  # Prefer implementation after @overload.
                    )
                    if isinstance(node, ast.ClassDef):
                        # The layout's documented meaning is its own concept,
                        # separate from implementation methods and constructor API.
                        if (
                            node.name in {"Layout", "Fragment", "PartialFragment"}
                            and "/layout/" in path
                        ):
                            doc_node = (
                                node.body[0]
                                if ast.get_docstring(node)
                                else next(
                                    (
                                        n.body[0]
                                        for n in node.body
                                        if isinstance(n, ast.FunctionDef)
                                        and n.name == "__init__"
                                        and ast.get_docstring(n)
                                    ),
                                    None,
                                )
                            )
                            if doc_node:
                                self.add(
                                    path,
                                    doc_node.lineno,
                                    doc_node.end_lineno,
                                    category="concept",
                                    name=node.name + " layout programming model",
                                    indexes=["concept"],
                                    description=ast.literal_eval(
                                        doc_node.value
                                    ).strip(),
                                    visibility="documentation",
                                    evidence_quality="source",
                                    related_concepts=["layout"],
                                    keywords=[
                                        "layout",
                                        "fragment",
                                        "index",
                                        "thread",
                                        "mapping",
                                        "布局",
                                        "编程模型",
                                    ],
                                )
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef) and (
                                not child.name.startswith("_")
                                or module + "." + node.name + "." + child.name
                                in aliases
                            ):
                                definitions[node.name + "." + child.name] = child
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    names = (
                        node.targets if isinstance(node, ast.Assign) else [node.target]
                    )
                    for target in names:
                        if (
                            isinstance(target, ast.Name)
                            and module + "." + target.id in aliases
                        ):
                            definitions[target.id] = node
            for local, node in definitions.items():
                qualified = module + "." + local
                public_aliases = aliases.get(qualified, [])
                if "." in local:
                    parent, _, method = local.partition(".")
                    public_aliases = [
                        *public_aliases,
                        *[
                            a + "." + method
                            for a in aliases.get(module + "." + parent, [])
                        ],
                    ]
                internal = (
                    local.startswith("_")
                    and not public_aliases
                    or ("/eager/" in path or "/tir/" in path)
                    and not public_aliases
                )
                if internal and not compiler:
                    continue
                category = (
                    "compiler"
                    if compiler
                    else "instruction"
                    if Path(path).stem
                    in {
                        "builtin",
                        "copy_op",
                        "gemm_op",
                        "reduce_op",
                        "atomic",
                        "intrinsics",
                    }
                    else "api"
                )
                doc = (
                    ast.get_docstring(node) or ""
                    if isinstance(
                        node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)
                    )
                    else ""
                )
                description = (
                    doc.split("\n\n")[0].replace("\n", " ")
                    if doc
                    else f"{qualified}: source declaration; consult its implementation and related examples."
                )
                start = min(
                    [
                        node.lineno,
                        *[d.lineno for d in getattr(node, "decorator_list", [])],
                    ]
                )
                signature, params, returns = function_contract(node, doc)
                self.add(
                    path,
                    start,
                    node.end_lineno,
                    category=category,
                    name=qualified,
                    indexes=["compiler"] if compiler else ["api"],
                    description=description,
                    aliases=sorted(public_aliases),
                    signature=signature,
                    parameters=params,
                    returns=returns,
                    constraints=source_notes(
                        doc, r"must|required|cannot|only|constraint|align|synchron|wait"
                    ),
                    hardware_mapping=source_notes(
                        doc,
                        r"CUDA|HIP|Metal|WebGPU|tensor core|cp\.async|TMA|TMEM|WGMMA|MFMA|Hopper|Blackwell|Ampere",
                    ),
                    visibility="public"
                    if public_aliases
                    else "internal"
                    if internal or compiler
                    else "module",
                    # All files involved in static exports matter if the facade changes.
                    dependencies=facade_paths if public_aliases else [],
                    symbols=sorted(set(re.findall(r"\b(?:T|tilelang)(?:\.\w+)+", doc))),
                    cautions=[
                        "Hardware support is target- and lowering-dependent; this signature is not a GPU execution result."
                    ],
                )
        unresolved = sorted(
            alias
            for qualified, aa in aliases.items()
            if not any(u.name == qualified for u in self.units.values())
            for alias in aa
        )
        self.diagnostics.append(
            "Exports without extracted definition (external/dynamic/private): "
            + ", ".join(unresolved)
        )

    def markdown(self):
        roots = [self.root / "docs", self.root / "examples"]
        allowed_docs = {
            "programming_guides",
            "get_started",
            "tutorials",
            "deeplearning_operators",
            "compiler_internals",
            "runtime_internals",
            "tools",
        }
        for root in roots:
            for file in sorted(root.rglob("*.md")):
                path = file.relative_to(self.root).as_posix()
                if path.startswith("docs/") and path.split("/")[1] not in allowed_docs:
                    continue
                text = self.read(file)
                lines, headings, stack, fence = text.splitlines(), [], [], None
                for i, line in enumerate(lines, 1):
                    marker = re.match(r"^\s*(`{3,}|~{3,})", line)
                    if marker:
                        chars = marker[1]
                        if fence is None:
                            fence = chars
                        elif chars[0] == fence[0] and len(chars) >= len(fence):
                            fence = None
                        continue
                    match = (
                        re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
                        if fence is None
                        else None
                    )
                    if match:
                        level, title = len(match[1]), match[2]
                        while stack and stack[-1][0] >= level:
                            stack.pop()
                        stack.append((level, title))
                        headings.append((i, " / ".join(t for _, t in stack)))
                if not headings or headings[0][0] > 1:
                    headings.insert(0, (1, file.stem))
                for pos, (start, name) in enumerate(headings):
                    end = (
                        headings[pos + 1][0] - 1
                        if pos + 1 < len(headings)
                        else len(lines)
                    )
                    body = "\n".join(lines[start:end]).strip()
                    if not body:
                        continue
                    category = (
                        "compiler"
                        if any(
                            part in path
                            for part in (
                                "compiler_internals/",
                                "runtime_internals/",
                                "/tools/lower",
                                "/tools/pass",
                                "/tools/autodd",
                            )
                        )
                        else "concept"
                    )
                    group = families(path + " " + name)
                    indexes = ["compiler"] if category == "compiler" else ["concept"]
                    if "/deeplearning_operators/" in path or (
                        path.startswith("examples/") and group
                    ):
                        category, indexes = "operator", ["operator", "concept"]
                    prose = re.split(r"\n\s*\n", body)[0]
                    self.add(
                        path,
                        start,
                        end,
                        category=category,
                        name=name,
                        indexes=indexes,
                        description=prose,
                        visibility="documentation",
                        evidence_quality="documentation",
                        examples=[
                            {"code": block}
                            for block in re.findall(
                                r"```(?:python|py)\s*\n(.*?)```", body, re.S
                            )
                        ],
                        symbols=sorted(
                            set(re.findall(r"\b(?:T|tilelang)(?:\.\w+)+", body))
                        ),
                    )

    def examples(self):
        for file in sorted((self.root / "examples").rglob("*.py")):
            if (
                file.name.startswith(("test_", "regression_", "benchmark"))
                or file.name == "conftest.py"
            ):
                continue
            path = file.relative_to(self.root).as_posix()
            text = self.read(file)
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                self.diagnostics.append(f"Example parse skipped: {path}:{exc.lineno}")
                continue
            context = "\n".join(
                ast.get_source_segment(text, n)
                for n in tree.body
                if isinstance(
                    n, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)
                )
            )
            top_functions = {
                n.name
                for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef))
            }
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef):
                    continue
                segment = ast.get_source_segment(text, node)
                if not re.search(r"\bT\.(?:Kernel|prim_func)\b", segment):
                    continue
                start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
                segment = "\n".join(text.splitlines()[start - 1 : node.end_lineno])
                doc = ast.get_docstring(node) or ""
                symbols = sorted(
                    set(re.findall(r"\b(?:T|tilelang)(?:\.\w+)+", segment))
                )
                deps = sorted(
                    {
                        n.func.id
                        for n in ast.walk(node)
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id in top_functions
                        and n.func.id != node.name
                    }
                )
                signature, params, returns = function_contract(node, doc)
                family = families(path)
                structure = operator_structure(node)
                self.add(
                    path,
                    start,
                    node.end_lineno,
                    category="example",
                    name=path + "::" + node.name,
                    indexes=["example", "operator"],
                    visibility="example",
                    evidence_quality="example",
                    description=doc.split("\n\n")[0]
                    if doc
                    else f"{' / '.join(family) or 'TileLang'} kernel constructor {node.name}; source reference, not measured or validated here.",
                    signature=signature,
                    parameters=params,
                    returns=returns,
                    symbols=symbols,
                    context=context,
                    operator_structure=structure,
                    dependencies=deps,
                    cautions=[
                        "Preserve imports, constants, nested functions and referenced helpers; verify shapes, dtype and target before adapting.",
                        "GPU compilation, numerical correctness and performance not run by the knowledge builder.",
                    ],
                )

    def cpp(self):
        # Explicit semantic declarations, not arbitrary file/line-sized windows.
        declaration = re.compile(
            r"(?m)^\s*(?:class|struct)\s+(\w+)[^;{}]*\{|^[ \t]*(?:[\w:<>,*&]+[ \t]+)+(\w+(?:::\w+)*)\s*\([^;{}]*?\)\s*(?:const\s*)?(?:final\s*|override\s*)?\{"
        )
        allowed = (
            "src/transform/",
            "src/op/",
            "src/layout/",
            "src/backend/",
            "src/cuda/",
            "src/rocm/",
            "src/cpu/",
            "src/metal/",
            "src/webgpu/",
        )
        for file in sorted((self.root / "src").rglob("*")):
            path = file.relative_to(self.root).as_posix()
            if file.suffix not in {".h", ".cc"} or not (
                path.startswith(allowed) or path == "src/ir.cc"
            ):
                continue
            text = self.read(file)
            masked = mask_cpp(text)
            last_end, found = -1, 0
            for match in declaration.finditer(masked):
                if match.start() < last_end:
                    continue
                name = match[1] or match[2]
                if name in {"if", "for", "while", "switch"}:
                    continue
                opening, depth, end = match.end() - 1, 0, None
                for i in range(opening, len(masked)):
                    depth += (masked[i] == "{") - (masked[i] == "}")
                    if depth == 0:
                        end = i + 1
                        break
                if end is None:
                    self.diagnostics.append(f"Unclosed C++ declaration: {path}:{name}")
                    continue
                last_end, found = end, found + 1
                start_line = text.count("\n", 0, match.start()) + 1
                end_line = text.count("\n", 0, end) + 1
                component = (
                    "IR / tile op"
                    if "/op/" in path or path == "src/ir.cc"
                    else "codegen"
                    if "/codegen/" in path
                    else "pass"
                    if "/transform/" in path
                    else "compiler component"
                )
                self.add(
                    path,
                    start_line,
                    end_line,
                    category="compiler",
                    name=f"{path}::{name}",
                    identity=f"{name}::{text[match.start() : opening].strip()}",
                    indexes=["compiler"],
                    aliases=[name],
                    description=f"{component}: {name}. Definition in {path}; structural extraction, inspect source for precise invariants.",
                    visibility="internal",
                    evidence_quality="structural",
                    signature=text[match.start() : opening].strip(),
                    cautions=[
                        "Internal C++ component, not a public Python DSL API. Conservative brace scanner, not a C++ type checker."
                    ],
                )
            if not found:
                self.diagnostics.append(f"No supported named C++ declarations: {path}")

    def connect(self):
        by_alias = defaultdict(list)
        for unit in self.units.values():
            for alias in [unit.name, *unit.aliases]:
                by_alias[alias].append(unit.id)
        example_refs = defaultdict(list)
        for unit in list(self.units.values()):
            related = set(unit.related_concepts)
            for symbol in unit.symbols:
                related.update(by_alias.get(symbol, []))
                if unit.category == "example":
                    for uid in by_alias.get(symbol, []):
                        example_refs[uid].append(
                            {
                                "unit_id": unit.id,
                                "source_location": unit.source_location.model_dump(),
                            }
                        )
            self.units[unit.id] = unit.model_copy(
                update={"related_concepts": sorted(related - {unit.id})}
            )
        for uid, examples in example_refs.items():
            self.units[uid] = self.units[uid].model_copy(update={"examples": examples})

    def run(self) -> list[KnowledgeUnit]:
        self.python()
        self.markdown()
        self.examples()
        self.cpp()
        self.connect()
        self.diagnostics = sorted(set(self.diagnostics))
        return sorted(self.units.values(), key=lambda u: u.id)


def function_contract(node, doc: str) -> tuple[str, list[dict], str]:
    if isinstance(node, ast.ClassDef):
        initializer = next(
            (
                n
                for n in node.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__"
            ),
            None,
        )
        if initializer:
            signature, params, _ = function_contract(
                initializer, ast.get_docstring(initializer) or doc
            )
            return signature.replace("__init__", node.name, 1), params, node.name
        return (
            "class "
            + node.name
            + "("
            + ", ".join(ast.unparse(b) for b in node.bases)
            + ")",
            [],
            "",
        )
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return (ast.unparse(node).split("\n")[0], [], "")
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
    entries = [
        (
            a,
            d,
            "positional_only" if i < len(args.posonlyargs) else "positional_or_keyword",
        )
        for i, (a, d) in enumerate(zip(positional, defaults))
    ]
    entries += [
        (a, d, "keyword_only") for a, d in zip(args.kwonlyargs, args.kw_defaults)
    ]
    if args.vararg:
        entries.append((args.vararg, None, "var_positional"))
    if args.kwarg:
        entries.append((args.kwarg, None, "var_keyword"))
    params = []
    for arg, default, kind in entries:
        description = parameter_doc(doc, arg.arg)
        params.append(
            {
                "name": arg.arg,
                "kind": kind,
                "annotation": ast.unparse(arg.annotation) if arg.annotation else "",
                "default": ast.unparse(default) if default else None,
                "description": description,
            }
        )
    returns = ast.unparse(node.returns) if node.returns else ""
    return (
        f"{node.name}({ast.unparse(args)})" + (f" -> {returns}" if returns else ""),
        params,
        returns,
    )


def parameter_doc(doc: str, name: str) -> str:
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        match = re.match(
            r"^(\s*)" + re.escape(name) + r"(?:\s*\([^\n]*\))?\s*:\s*(.*)", line
        )
        if not match:
            continue
        parts, indent = [match[2].strip()], len(match[1])
        for more in lines[i + 1 :]:
            if not more.strip() or len(more) - len(more.lstrip()) <= indent:
                break
            parts.append(more.strip())
        return " ".join(parts)
    return ""


def source_notes(doc: str, pattern: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\n\s*\n", doc)
        if re.search(pattern, part, re.I)
    ]


def operator_structure(node: ast.FunctionDef) -> dict:
    """Describe source operations without inferring their runtime layout or speed."""
    result = {
        "control_flow": [],
        "allocations": [],
        "transfers": [],
        "compute": [],
        "synchronization": [],
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        symbol = ast.unparse(child.func)
        if not symbol.startswith("T."):
            continue
        name = symbol[2:]
        category = (
            "control_flow"
            if name
            in {"Kernel", "Pipelined", "Parallel", "serial", "unroll", "Persistent"}
            else "allocations"
            if name.startswith("alloc_") or name == "empty"
            else "transfers"
            if name in {"copy", "async_copy", "tma_copy", "transpose"}
            else "compute"
            if name.startswith(("gemm", "reduce_", "warp_reduce_"))
            or name in {"exp", "exp2", "rsqrt"}
            else "synchronization"
            if any(part in name for part in ("barrier", "wait", "sync", "commit"))
            else None
        )
        if category:
            result[category].append(
                {
                    "symbol": symbol,
                    "line": child.lineno,
                    "arguments": [ast.unparse(a) for a in child.args],
                    "keywords": {
                        k.arg or "**": ast.unparse(k.value) for k in child.keywords
                    },
                }
            )
    return result


def mask_cpp(text: str) -> str:
    """Hide comments/strings while preserving offsets, newlines and braces in code."""
    pattern = r'//[^\n]*|/\*[\s\S]*?\*/|R"([^ ()\\\t\r\n]*)\([\s\S]*?\)\1"|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27'
    return re.sub(
        pattern, lambda m: "".join("\n" if c == "\n" else " " for c in m[0]), text
    )
