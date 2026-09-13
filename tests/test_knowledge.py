import ast
import json
import shutil
from types import SimpleNamespace

import pytest

from kernellens.application import AgentApplication
from kernellens.cli import parser
from kernellens.config import Settings, load_settings
from kernellens.domain.action import CallToolAction, FinishAction
from kernellens.domain.task import TaskType
from kernellens.knowledge.build import dump, make_index
from kernellens.knowledge.bundle import export_bundle
from kernellens.knowledge.contracts import check_calls
from kernellens.knowledge.extract import Extractor, PythonSurface, function_contract
from kernellens.knowledge.schema import KnowledgeUnit, SourceLocation, sha256, unit_id
from kernellens.knowledge.search import KnowledgeBase, KnowledgeError, encoded
from kernellens.knowledge.terms import route
from kernellens.review import ReportReviewer
from kernellens.runtime.handlers import FinishRejected
from kernellens.security import Redactor
from kernellens.tools.registry import ToolRegistry
from kernellens.tools.workspace import Workspace, WorkspaceError


@pytest.fixture
def delivery(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    units = []
    definitions = [
        (
            "instruction",
            "tilelang.cuda.language.copy_op.copy",
            ["api"],
            ["T.copy"],
            "def copy(src, dst, *, disable_tma=False):\n    '''Copy data with synchronous semantics.'''\n    return dst",
            "cuda",
        ),
        (
            "concept",
            "Software pipeline synchronization",
            ["concept"],
            [],
            "Pipeline stages overlap copies and compute. Wait before consuming an explicit asynchronous copy.",
            "",
        ),
        (
            "concept",
            "Understanding targets Metal",
            ["concept"],
            [],
            "Metal target is for Apple GPUs. Select a matching dialect.",
            "metal",
        ),
        (
            "example",
            "examples/gemm/gemm.py::matmul",
            ["example", "operator"],
            [],
            "def matmul(A, B):\n    return A @ B\n",
            "",
        ),
        (
            "operator",
            "GEMM tiled matrix multiplication",
            ["operator"],
            [],
            "GEMM uses shared input tiles and a fragment accumulator.",
            "",
        ),
        (
            "compiler",
            "tilelang.transform.LayoutInference",
            ["compiler"],
            ["LayoutInference"],
            "def LayoutInference():\n    '''Infer memory layout and validate constraints.'''\n    return None",
            "",
        ),
    ]
    for i, (category, name, indexes, aliases, content, target) in enumerate(
        definitions
    ):
        path = f"unit_{i}.py"
        (repo / path).write_text(content)
        signature, parameters, returns = (
            function_contract(ast.parse(content).body[0], "")
            if category in {"instruction", "compiler", "example"}
            else ("", [], "")
        )
        units.append(
            KnowledgeUnit(
                id=unit_id(category, path, name),
                category=category,
                name=name,
                indexes=indexes,
                description=content,
                when_to_use=name,
                source_location=SourceLocation(
                    path=path, start_line=1, end_line=len(content.splitlines())
                ),
                keywords=[name],
                layer="implementation" if category == "compiler" else "user",
                visibility="public"
                if aliases
                else "example"
                if category == "example"
                else "documentation",
                aliases=aliases,
                signature=signature,
                parameters=parameters,
                returns=returns,
                source_revision="fixture",
                source_hash=sha256(content.encode()),
                content="\n".join(content.splitlines()),
                evidence_quality="source",
                targets=[target] if target else [],
            )
        )
    directory = repo / "tilelang_knowledge"
    directory.mkdir()
    make_index(directory / "index.sqlite3", units)
    dump(
        directory / "manifest.json",
        {
            "schema_version": 1,
            "repo_relative": "..",
            "source_revision": "fixture",
            "public_exports": {alias: u.name for u in units for alias in u.aliases},
            "source_files": {u.source_location.path: u.source_hash for u in units},
            "delivery_hashes": {
                "index.sqlite3": sha256((directory / "index.sqlite3").read_bytes())
            },
            "indexes": {},
            "limitations": ["fixture"],
        },
    )
    return directory, units


def test_cycle_exports_and_override():
    sources = {
        "tilelang/language/__init__.py": "from .cuda import *\nfrom .cuda import __all__ as __all__",
        "tilelang/language/cuda.py": "from .common import *\nfrom .common import __all__ as _COMMON\ndef copy(src, dst, *, disable_tma=False): pass\n__all__=tuple(dict.fromkeys((*_COMMON, 'copy')))",
        "tilelang/language/common.py": "from .eager import prim_func\ndef copy(src, dst): pass\n__all__=['prim_func', 'copy']",
        "tilelang/language/eager.py": "from .common import copy\ndef prim_func(fn): return fn",
    }
    surface = PythonSurface(sources, [])
    surface.resolve(["tilelang.language"])
    exported = surface.exports("tilelang.language")[0]
    assert exported["copy"] == "tilelang.language.cuda.copy"
    assert exported["prim_func"] == "tilelang.language.eager.prim_func"


def test_contract_preserves_keyword_only_and_defaults():
    node = ast.parse(
        "def copy(src, dst, /, *, disable_tma=False, scope: str='shared') -> int: pass"
    ).body[0]
    signature, parameters, returns = function_contract(node, "")
    assert "/" in signature and "*" in signature
    assert parameters[0]["kind"] == "positional_only"
    assert parameters[2]["kind"] == "keyword_only"
    assert parameters[2]["default"] == "False"
    assert returns == "int"


def test_markdown_semantic_boundary_ignores_fenced_headings(tmp_path):
    directory = tmp_path / "docs/programming_guides"
    directory.mkdir(parents=True)
    content = "# Guide\nIntro.\n## Copy\n```python\n# still code\nT.copy(A, B)\n```\nDetails.\n## Wait\nWait here.\n"
    (directory / "instructions.md").write_text(content)
    extractor = Extractor(tmp_path, "fixture")
    extractor.markdown()
    chunks = list(extractor.units.values())
    copy = next(u for u in chunks if u.name == "Guide / Copy")
    assert "# still code\nT.copy" in copy.content
    assert "Wait" not in copy.content
    assert copy.examples[0]["code"] == "# still code\nT.copy(A, B)\n"


def test_example_is_whole_constructor_with_dependencies(tmp_path):
    directory = tmp_path / "examples/gemm"
    directory.mkdir(parents=True)
    text = "import tilelang.language as T\nM = 128\ndef helper(x): return x\n\ndef matmul(A):\n    @T.prim_func\n    def kernel():\n        with T.Kernel(1):\n            helper(A)\n    return kernel\n"
    (directory / "gemm.py").write_text(text)
    extractor = Extractor(tmp_path, "fixture")
    extractor.examples()
    unit = next(iter(extractor.units.values()))
    assert "return kernel" in unit.content
    assert "M = 128" in unit.context
    assert unit.dependencies == ["helper"]
    assert len(extractor.units) == 1


def test_cpp_balancing_ignores_literals_and_comments(tmp_path):
    directory = tmp_path / "src/op"
    directory.mkdir(parents=True)
    text = 'class CopyNode {\n const char* s = "}";\n /* } */\n void Lower() {}\n};\n'
    (directory / "copy.h").write_text(text)
    extractor = Extractor(tmp_path, "fixture")
    extractor.cpp()
    unit = next(iter(extractor.units.values()))
    assert "void Lower() {}" in unit.content
    assert unit.visibility == "internal"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("T.copy 参数", "api"),
        ("流水线的语义", "concept"),
        ("生成一个 GEMM 算子", "operator"),
        ("LayoutInference 报错", "compiler"),
        ("Metal 后端支持", "target"),
        ("GEMM example", "example"),
    ],
)
def test_question_routing(query, expected):
    assert route(query)[0] == expected


def test_exact_symbol_unknown_symbol_and_limits(delivery):
    directory, _ = delivery
    kb = KnowledgeBase(directory)
    try:
        answer = kb.search("T.copy 参数", top_k=1)
        assert answer["results"][0]["name"] == "tilelang.cuda.language.copy_op.copy"
        assert answer["results"][0]["match"] == "exact_symbol"
        for budget in [1500, 2666, 5000, 10000, 20000]:
            result = kb.search("GEMM pipeline copy", max_chars=budget)
            assert result["context_chars"] == len(encoded(result)) <= budget
        assert kb.search("T.not_a_real_api 参数")["status"] == "no_match"
        assert kb.search("T.copy", target="hip")["results"] == []
        assert kb.validate()["status"] == "passed"
    finally:
        kb.close()


def test_stale_source_is_not_returned_as_evidence(delivery):
    directory, units = delivery
    kb = KnowledgeBase(directory)
    try:
        (directory.parent / units[0].source_location.path).write_text("changed")
        result = kb.search("T.copy")
        assert result["status"] == "stale"
        assert not result["results"]
        with pytest.raises(KnowledgeError, match="Stale"):
            kb.read(units[0].id)
    finally:
        kb.close()


def test_index_tampering_rejected(delivery):
    directory, _ = delivery
    with (directory / "index.sqlite3").open("ab") as file:
        file.write(b"tampered")
    with pytest.raises(KnowledgeError, match="hash mismatch"):
        KnowledgeBase(directory)


def test_knowledge_tools_do_not_expand_file_workspace(delivery, tmp_path):
    directory, units = delivery
    workspace = tmp_path / "task"
    workspace.mkdir()
    kb = KnowledgeBase(directory)
    registry = ToolRegistry(Workspace(workspace), "test", Redactor(), knowledge=kb)
    try:
        result = registry(
            CallToolAction("read_knowledge", {"unit_id": units[0].id}, "verify API")
        )
        assert "Copy data" in result.content
        assert registry.knowledge_reads[units[0].id]["complete"]
        with pytest.raises(WorkspaceError):
            registry.workspace.read_file(
                str(directory.parent / units[0].source_location.path)
            )
    finally:
        kb.close()


def test_application_prefetch_is_in_first_model_request_and_trace(delivery, tmp_path):
    directory, units = delivery
    workspace = tmp_path / "task"
    workspace.mkdir()
    requests = []

    def transport(payload, timeout):
        requests.append(payload)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "read-api",
                        "type": "function",
                        "function": {
                            "name": "read_knowledge",
                            "arguments": json.dumps({"unit_id": units[0].id}),
                        },
                    }
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "T.copy 的同步语义见检索源码。[E1][E2] GPU 未执行。",
            }
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        }

    app = AgentApplication(
        Workspace(workspace),
        Settings(
            base_url="http://localhost/v1",
            model="fixture",
            api_key="fixture-key",
            knowledge_dir=str(directory),
        ),
        emit=lambda _: None,
        transport=transport,
    )
    try:
        session = app.store.create_session()
        result = app.run(session, "T.copy 的同步语义是什么")
        assert result.status == "completed", result.answer
        assert len(requests) == 2
        assert units[0].id in json.dumps(requests[0]["messages"])
        assert "synchronous semantics" in json.dumps(requests[1]["messages"])
        assert any(m["role"] == "tool" for m in requests[1]["messages"])
        steps = app.store.steps(result.run_id)
        assert steps[0]["event"] == "knowledge_prefetch"
        assert steps[1]["action"]["tool_name"] == "read_knowledge"
        details = json.loads(
            (workspace / ".kernellens/runs" / result.run_id / "result.json").read_text()
        )
        assert details["evidence"][0]["retrieval"]["unit_ids"] == [units[0].id]
    finally:
        app.close()


def test_knowledge_setting_precedence():
    settings = load_settings(
        {"KERNELLENS_KNOWLEDGE_DIR": "/env/kb"}, overrides={"knowledge_dir": "/cli/kb"}
    )
    assert settings.knowledge_dir == "/cli/kb"


@pytest.fixture
def portable_delivery(delivery, tmp_path):
    directory, units = delivery
    (directory.parent / "LICENSE").write_text("Fixture upstream license\n")
    destination = tmp_path / "portable" / "knowledge"
    result = export_bundle(directory, destination)
    assert result["unit_count"] == len(units)
    # Only remove this test's synthetic source. The exported data must survive.
    shutil.rmtree(directory.parent)
    return destination, units


def test_bundle_reads_and_checks_calls_without_original_source(portable_delivery):
    directory, units = portable_delivery
    kb = KnowledgeBase(directory)
    try:
        assert kb.repo is None
        assert kb.delivery_mode == "snapshot"
        assert (directory / "LICENSE").read_text() == "Fixture upstream license\n"
        result = kb.search("T.copy", max_chars=2500)
        assert result["results"][0]["id"] == units[0].id
        assert result["source_root"] == "https://github.com/tile-ai/tilelang"
        read = kb.read(units[0].id)
        assert "def copy" in read["content"]
        assert read["export_source_files_checked"] == 0
        check = check_calls(
            "import tilelang.language as T\nT.copy(A, B, disable_tma=True)", kb
        )
        assert check["status"] == "passed"
        validated = kb.validate()
        assert validated["status"] == "passed" and not validated["local_source_checked"]
    finally:
        kb.close()


def test_bundle_still_rejects_corrupt_index(portable_delivery):
    directory, _ = portable_delivery
    with (directory / "index.sqlite3").open("ab") as handle:
        handle.write(b"corrupt")
    with pytest.raises(KnowledgeError, match="hash mismatch"):
        KnowledgeBase(directory)


def test_bundle_export_rejects_stale_input_and_unowned_destination(delivery, tmp_path):
    directory, units = delivery
    (directory.parent / "LICENSE").write_text("Fixture license\n")
    destination = tmp_path / "owned-elsewhere"
    destination.mkdir()
    (destination / "manifest.json").write_text('{"generator":"someone-else"}')
    with pytest.raises(KnowledgeError, match="Refusing to replace"):
        export_bundle(directory, destination)
    (directory.parent / units[0].source_location.path).write_text("changed source")
    with pytest.raises(KnowledgeError, match="validation failed"):
        export_bundle(directory, tmp_path / "export")


def test_default_bundle_and_explicit_opt_out():
    from kernellens.knowledge import bundled_knowledge_dir

    assert load_settings({}).knowledge_dir == str(bundled_knowledge_dir())
    assert load_settings({"KERNELLENS_KNOWLEDGE_DIR": ""}).knowledge_dir == ""
    assert parser().parse_args([]).knowledge is None
    args = parser().parse_args(["--no-knowledge"])
    assert (
        load_settings({}, overrides={"knowledge_dir": args.knowledge}).knowledge_dir
        == ""
    )


def test_snapshot_agent_prefetch_and_evidence_without_source(
    portable_delivery, tmp_path
):
    directory, units = portable_delivery
    task = tmp_path / "task"
    task.mkdir()
    requests = []

    def transport(payload, timeout):
        requests.append(payload)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "snapshot-read",
                        "type": "function",
                        "function": {
                            "name": "read_knowledge",
                            "arguments": json.dumps({"unit_id": units[0].id}),
                        },
                    }
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "已读取知识包的 copy 说明。[E1][E2]",
            }
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        }

    app = AgentApplication(
        Workspace(task),
        Settings(
            base_url="http://localhost/v1",
            model="fixture",
            api_key="fixture-key",
            knowledge_dir=str(directory),
        ),
        emit=lambda _: None,
        transport=transport,
    )
    try:
        result = app.run(app.store.create_session(), "T.copy 的参数")
        assert result.status == "completed"
        assert units[0].id in json.dumps(requests[0]["messages"])
        assert "snapshot" in json.dumps(requests[0]["messages"])
        report = json.loads(
            (task / ".kernellens/runs" / result.run_id / "result.json").read_text()
        )
        evidence = report["evidence"][-1]
        assert evidence["path"] == str(directory / "index.sqlite3")
        assert evidence["sha256"] == sha256((directory / "index.sqlite3").read_bytes())
        assert (
            evidence["retrieval"]["source_location"]
            == units[0].source_location.model_dump()
        )
        assert evidence["retrieval"]["delivery_mode"] == "snapshot"
    finally:
        app.close()


def test_finish_rejects_missing_accumulator_initialization(delivery, tmp_path):
    directory, units = delivery
    workspace = tmp_path / "task"
    workspace.mkdir()
    kb = KnowledgeBase(directory)
    registry = ToolRegistry(Workspace(workspace), "test", Redactor(), knowledge=kb)
    try:
        for unit in (units[0], units[3]):
            registry(CallToolAction("read_knowledge", {"unit_id": unit.id}, "source"))
        source = 'def kernel():\n acc = T.alloc_fragment((64, 64), "float32")\n T.gemm(A, B, acc)'
        result = registry(
            CallToolAction(
                "write_file", {"path": "gemm.py", "content": source}, "candidate"
            )
        )
        saved = json.loads(result.content)
        registry(CallToolAction("check_python", {"path": "gemm.py"}, "check"))
        state = SimpleNamespace(request=SimpleNamespace(task_type=TaskType.GENERATE))
        action = FinishAction("候选已检查。[E1]", "done")
        reviewer = ReportReviewer(registry)
        with pytest.raises(FinishRejected, match="初始化"):
            reviewer(state, action)
        corrected = source.replace(" T.gemm", " T.clear(acc)\n T.gemm")
        registry(
            CallToolAction(
                "write_file",
                {
                    "path": "gemm.py",
                    "content": corrected,
                    "expected_sha256": saved["sha256"],
                },
                "initialize",
            )
        )
        registry(CallToolAction("check_python", {"path": "gemm.py"}, "recheck"))
        assert reviewer(state, action)
    finally:
        kb.close()


def test_public_keyword_contract_and_unknown_are_separate(delivery):
    kb = KnowledgeBase(delivery[0])
    try:
        prefix = "import tilelang.language as T\n"
        good = check_calls(prefix + "T.copy(A, B, disable_tma=True)", kb)
        assert good["status"] == "passed"
        bad = check_calls(prefix + "T.copy(A, B, imagined_option=7)", kb)
        assert bad["status"] == "failed"
        assert "imagined_option" in bad["calls"][0]["issues"][0]
        unknown = check_calls(prefix + "T.unknown_api(A)", kb)
        assert unknown["status"] == "inconclusive"
        assert unknown["gpu_validation"] == "not_run"
        assert (
            check_calls(prefix + "T.copy(A, B, **options)", kb)["status"]
            == "inconclusive"
        )
    finally:
        kb.close()


def test_expansion_does_not_pollute_api_index_or_unbound_context(delivery):
    directory, units = delivery
    original = KnowledgeBase(directory)
    before = original.search("T.copy")
    original.close()
    # 1000 compiler-only records mention copy; they must not enter an API query.
    noise = [
        units[-1].model_copy(
            update={
                "id": unit_id("compiler", "noise", str(i)),
                "name": f"CompilerCopy{i}",
                "description": "copy shared global pipeline GEMM",
                "aliases": [],
            }
        )
        for i in range(1000)
    ]
    replacement = directory / "next.sqlite3"
    make_index(replacement, [*units, *noise])
    replacement.replace(directory / "index.sqlite3")
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["delivery_hashes"]["index.sqlite3"] = sha256(
        (directory / "index.sqlite3").read_bytes()
    )
    dump(directory / "manifest.json", manifest)
    expanded = KnowledgeBase(directory)
    try:
        after = expanded.search("T.copy")
        assert [u["id"] for u in before["results"]] == [
            u["id"] for u in after["results"]
        ]
        assert "compiler" not in after["indexes"]
        compiler = expanded.search("copy error", max_chars=3000)
        assert compiler["candidate_counts"]["compiler"] == 100
        assert len(encoded(compiler)) <= 3000
    finally:
        expanded.close()


def test_pagination_preserves_complete_semantic_source(delivery):
    directory, units = delivery
    old = units[3]
    content = (
        "def matmul(A, B):\n"
        + "\n".join(f"    x{i} = A @ B" for i in range(350))
        + "\n    return x349"
    )
    source = directory.parent / old.source_location.path
    source.write_text(content)
    replacement_unit = old.model_copy(
        update={
            "content": content,
            "source_hash": sha256(content.encode()),
            "source_location": old.source_location.model_copy(
                update={"end_line": len(content.splitlines())}
            ),
        }
    )
    units = [replacement_unit if u.id == old.id else u for u in units]
    replacement = directory / "next.sqlite3"
    make_index(replacement, units)
    replacement.replace(directory / "index.sqlite3")
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["delivery_hashes"]["index.sqlite3"] = sha256(
        (directory / "index.sqlite3").read_bytes()
    )
    manifest["source_files"][old.source_location.path] = replacement_unit.source_hash
    dump(directory / "manifest.json", manifest)
    kb = KnowledgeBase(directory)
    try:
        start, parts = 0, []
        for _ in range(20):
            result = kb.read(old.id, start_line=start, max_chars=2000)
            assert result["context_chars"] == len(encoded(result)) <= 2000
            parts.append(result["content"])
            if not result["truncated"]:
                break
            assert result["next_line"] > start
            start = result["next_line"]
        assert "".join(parts).rstrip("\n") == content
    finally:
        kb.close()


def test_tool_serialization_respects_requested_budget(delivery, tmp_path):
    directory, units = delivery
    workspace = tmp_path / "task"
    workspace.mkdir()
    kb = KnowledgeBase(directory)
    try:
        registry = ToolRegistry(Workspace(workspace), "test", Redactor(), knowledge=kb)
        for name, arguments in [
            ("search_knowledge", {"query": "T.copy", "max_chars": 2000}),
            ("read_knowledge", {"unit_id": units[0].id, "max_chars": 2000}),
        ]:
            observation = registry(
                CallToolAction(name, arguments, "check context budget")
            )
            result = json.loads(observation.content)
            assert result["context_chars"] == len(observation.content) <= 2000
            assert result["evidence_id"].startswith("E")
    finally:
        kb.close()


def test_prefetch_full_source_counts_only_when_the_whole_unit_is_present(
    delivery, tmp_path
):
    directory, units = delivery
    workspace = tmp_path / "task"
    workspace.mkdir()
    kb = KnowledgeBase(directory)
    try:
        registry = ToolRegistry(Workspace(workspace), "test", Redactor(), knowledge=kb)
        observation = registry(
            CallToolAction(
                "search_knowledge",
                {
                    "query": "生成 GEMM",
                    "include_source": True,
                    "max_chars": 7000,
                    "top_k": 3,
                },
                "prepare grounded context",
            )
        )
        response = json.loads(observation.content)
        for item in response["results"]:
            if item["source_complete"]:
                original = next(u for u in units if u.id == item["id"])
                assert item["excerpt"] == original.content
                assert not item["excerpt_truncated"]
                assert registry.knowledge_reads[item["id"]]["complete"]
        assert registry.knowledge_reads[units[3].id]["complete"]
        assert len(observation.content) <= 7000
    finally:
        kb.close()
