"""Conservative checks for explicit GEMM shape/dtype declarations.

This checks declarations, not the mathematics or TileLang API validity. It never
evaluates Python. Unknown expressions stay inconclusive instead of passing.
"""

import ast
import re


def explicit_gemm_constraints(goal: str) -> dict:
    if not re.search(r"gemm|矩阵乘", goal, re.I):
        return {}
    found = {}
    chain = re.search(r"M\s*=\s*N\s*=\s*K\s*=\s*(\d+)", goal, re.I)
    if chain:
        found.update({name: int(chain[1]) for name in "MNK"})
    for name in "MNK":
        match = re.search(rf"\b{name}\s*=\s*(\d+)", goal, re.I)
        if match:
            found[name] = int(match[1])
    dtype = r"(float16|float32|bfloat16)"
    for names in ("A/B/C", "A/B", "C"):
        match = re.search(rf"\b{names}\s*(?:为|是|=|:|：)?\s*{dtype}\b", goal, re.I)
        if match:
            for name in names.split("/"):
                found[name] = match[1].lower()
    accum = re.search(
        rf"(?:累加(?:类型)?|accum(?:_dtype)?)\s*(?:为|=|:|：)?\s*{dtype}", goal, re.I
    )
    if accum:
        found["accum"] = accum[1].lower()
    return found


def declared_gemm_signature(source: str) -> dict:
    tree = ast.parse(source)
    values = {}
    dtype_namespaces = {"T", "tilelang.language"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tilelang.language":
                    dtype_namespaces.add(alias.asname or alias.name)

    def bind(name, value):
        # Different scopes/reassignments cannot be resolved safely by this
        # deliberately small analyzer. Keep ambiguity instead of picking last.
        if name in values and values[name] != value:
            values[name] = None
        else:
            values[name] = value

    def literal(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and ast.unparse(node.value) in dtype_namespaces
            and node.attr in {"float16", "float32", "bfloat16"}
        ):
            return node.attr
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(literal(item) for item in node.elts)
        return None

    # Resolve literal global assignments and function defaults without executing.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = literal(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bind(target.id, value)
                if isinstance(target, ast.Tuple) and isinstance(value, tuple):
                    for name, item in zip(target.elts, value):
                        if isinstance(name, ast.Name) and item is not None:
                            bind(name.id, item)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            bind(node.target.id, literal(node.value))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument, default in zip(
                node.args.args[-len(node.args.defaults) :], node.args.defaults
            ):
                value = literal(default)
                if value is not None:
                    bind(argument.arg, value)

    signature = {}

    def declare(name, value):
        previous = signature.get(name)
        signature[name] = value if previous in (None, value) else "conflicting"

    def tensor(name, call):
        if name not in {"A", "B", "C"} or not isinstance(call, ast.Call):
            return
        symbol = call.func.attr if isinstance(call.func, ast.Attribute) else ""
        if symbol not in {"Tensor", "Buffer", "alloc_global", "empty"}:
            return
        shape = literal(call.args[0]) if call.args else None
        dtype = literal(call.args[1]) if len(call.args) > 1 else None
        for keyword in call.keywords:
            if keyword.arg == "dtype":
                dtype = literal(keyword.value)
        if dtype in {"float16", "float32", "bfloat16"}:
            declare(name, dtype)
        if isinstance(shape, tuple) and len(shape) == 2:
            axes = {"A": "MK", "B": "KN", "C": "MN"}[name]
            for axis, dimension in zip(axes, shape):
                if type(dimension) is int:
                    declare(axis, dimension)

    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            tensor(node.arg, node.annotation)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    tensor(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tensor(node.target.id, node.annotation)
            tensor(node.target.id, node.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "alloc_fragment"
        ):
            dtype = literal(node.args[1]) if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg == "dtype":
                    dtype = literal(keyword.value)
            if dtype in {"float16", "float32", "bfloat16"}:
                declare("accum", dtype)
    return signature


def check_gemm_constraints(source: str, expected: dict) -> dict:
    declared = declared_gemm_signature(source)
    mismatch = {
        key: {"expected": value, "declared": declared[key]}
        for key, value in expected.items()
        if key in declared and declared[key] != value
    }
    unknown = [key for key in expected if key not in declared]
    status = "failed" if mismatch else ("inconclusive" if unknown else "passed")
    return {
        "status": status,
        "expected": expected,
        "declared": declared,
        "mismatches": mismatch,
        "unresolved": unknown,
        "scope": "静态声明一致性；不证明计算语义、TileLang API、编译、数值或性能",
    }


def check_gemm_initialization(source: str) -> dict:
    """Check definite initialization of local fragment accumulators only.

    This is intentionally not a proof of GEMM mathematics. Branch joins and
    loops are conservative, and helper calls/dynamic clear flags stay unknown.
    """
    tree = ast.parse(source)
    calls = []

    def name(node):
        return node.id if isinstance(node, ast.Name) else None

    def symbol(node):
        return (
            node.func.attr
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            else ""
        )

    def block(statements, state):
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                block(statement.body, {})
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    key = name(target)
                    if key and symbol(statement.value) == "alloc_fragment":
                        state[key] = "uninitialized"
                    elif key in state:
                        state[key] = "unknown"
            elif isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                call = statement.value
                operation = symbol(call)
                if operation in {"clear", "fill"} and call.args:
                    key = name(call.args[0])
                    zero_fill = operation == "clear" or (
                        len(call.args) > 1
                        and isinstance(call.args[1], ast.Constant)
                        and call.args[1].value == 0
                    )
                    if key in state:
                        state[key] = "initialized" if zero_fill else "unknown"
                elif operation == "gemm":
                    output = (
                        call.args[2]
                        if len(call.args) > 2
                        else next(
                            (k.value for k in call.keywords if k.arg == "C"), None
                        )
                    )
                    key = name(output)
                    if key not in state:
                        continue
                    flag = next(
                        (k.value for k in call.keywords if k.arg == "clear_accum"),
                        call.args[6] if len(call.args) > 6 else ast.Constant(False),
                    )
                    current = state[key]
                    if (
                        not isinstance(flag, ast.Constant)
                        or type(flag.value) is not bool
                    ):
                        status = "inconclusive"
                    elif flag.value or current == "initialized":
                        status = "passed"
                    else:
                        status = (
                            "failed" if current == "uninitialized" else "inconclusive"
                        )
                    calls.append(
                        {"line": call.lineno, "accumulator": key, "status": status}
                    )
                    state[key] = "initialized" if status == "passed" else "unknown"
                else:
                    # An unmodeled helper can modify a buffer; do not infer its
                    # effect or incorrectly claim definite non-initialization.
                    for arg in call.args:
                        if name(arg) in state:
                            state[name(arg)] = "unknown"
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                block(statement.body, state)
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                block(statement.body, state.copy())
                block(statement.orelse, state.copy())
            elif isinstance(statement, ast.If):
                left, right = state.copy(), state.copy()
                block(statement.body, left)
                block(statement.orelse, right)
                for key in state.keys() | left.keys() | right.keys():
                    state[key] = (
                        left.get(key) if left.get(key) == right.get(key) else "unknown"
                    )

    block(tree.body, {})
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
        "calls": calls,
        "scope": "local fragment initialization before GEMM only; not full control-flow, numerical or GPU validation",
        "guidance": "For a fresh GEMM output, initialize the fragment with T.clear before the reduction loop. Preserve a source-backed alternative if applicable; do not clear partial sums on every loop iteration.",
    }
