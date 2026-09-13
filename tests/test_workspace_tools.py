import json

import pytest
from pydantic import ValidationError

from kernellens.domain.action import CallToolAction
from kernellens.domain.observation import ToolExecutionStatus
from kernellens.security import Redactor
from kernellens.storage import Store
from kernellens.tools.arguments import ReadReportArguments
from kernellens.tools.registry import ToolRegistry
from kernellens.tools.workspace import Workspace, WorkspaceError, digest


def test_schema_and_strict_arguments():
    schema = ReadReportArguments.model_json_schema()
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False
    assert ReadReportArguments(path=" report.json ").path == " report.json "
    for value in (None, True, 1, b"x", "", " \n "):
        with pytest.raises(ValidationError):
            ReadReportArguments(path=value)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        ".env",
        ".env.local",
        ".git/config",
        ".ssh/id_rsa",
        ".kernellens/history.sqlite3",
        "secret.pem",
    ],
)
def test_paths_are_scoped_and_secrets_excluded(tmp_path, name):
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        workspace.read_file(name)


def test_symlink_and_fifo_not_followed(tmp_path):
    workspace = Workspace(tmp_path)
    (tmp_path / "link").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(WorkspaceError, match="符号链接"):
        workspace.read_file("link/x")
    import os

    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(WorkspaceError, match="普通文件"):
        workspace.read_file("fifo")


def test_candidate_write_hash_conflict_backup_and_syntax(tmp_path):
    workspace = Workspace(tmp_path)
    created = workspace.write_file("artifacts/gemm.py", "x = 1\n", run_id="test")
    read = workspace.read_file(created["path"])
    assert read["sha256"] == created["sha256"]
    with pytest.raises(WorkspaceError, match="expected_sha256"):
        workspace.write_file(created["path"], "x = 2", run_id="test")
    updated = workspace.write_file(
        created["path"], "x = 2\n", created["sha256"], run_id="test"
    )
    assert (tmp_path / updated["backup"]).read_text() == "x = 1\n"
    assert workspace.check_python(created["path"])["syntax"] == "passed"
    workspace.write_file("broken.py", "x = (", run_id="test")
    assert workspace.check_python("broken.py")["syntax"] == "failed"
    assert workspace.search_text("x =", pattern="*.py")["matches"]


def test_report_matches_exact_candidate_and_preserves_source(tmp_path):
    workspace = Workspace(tmp_path)
    (tmp_path / "gemm.py").write_text("x=1")
    report = {
        "candidate_path": "gemm.py",
        "candidate_sha256": digest(b"x=1"),
        "correctness": "passed",
    }
    (tmp_path / "report.json").write_text(json.dumps(report))
    result = workspace.read_report("report.json")
    assert result["candidate_matches"] and result["source"] == "user_report"
    (tmp_path / "gemm.py").write_text("x=2")
    assert not workspace.read_report("report.json")["candidate_matches"]


def test_registry_errors_are_observations_and_never_echo_credentials(tmp_path):
    registry = ToolRegistry(Workspace(tmp_path), "test", Redactor("private-key"))
    bad = registry(CallToolAction("read_file", {"path": True}, "test"))
    assert bad.status is ToolExecutionStatus.FAILED
    assert "invalid_arguments" in bad.content
    assert (
        registry(CallToolAction("unknown", {}, "test")).status
        is ToolExecutionStatus.FAILED
    )
    (tmp_path / "notes.txt").write_text("private-key")
    feedback = registry(CallToolAction("read_file", {"path": "notes.txt"}, "test"))
    assert "private-key" not in feedback.content
    assert registry.evidence[0]["id"] == "E1"


def test_session_persists_and_is_workspace_local(tmp_path):
    workspace = Workspace(tmp_path)
    store = Store(workspace, Redactor("private-key"))
    session = store.create_session()
    store.message(session, "user", "private-key")
    run = store.start_run(session, "diagnose", "inspect")
    store.finish_run(run, "completed", "private-key", {}, [], {})
    store.close()
    reopened = Store(workspace, Redactor())
    assert reopened.resolve_session(session[:8]) == session
    assert reopened.history(session)[0]["content"] == "[REDACTED]"
    assert reopened.runs(session)[0]["status"] == "completed"
    reopened.close()


def test_report_comparison_rejects_wrong_workload_and_stale_code(tmp_path):
    workspace = Workspace(tmp_path)
    common = {
        "environment": {"gpu": "test"},
        "workload": {"M": 128},
        "measurement": {"method": "events"},
        "checks": {"correctness": "passed"},
    }
    for name, latency in (("base", [3, 4, 5]), ("candidate", [1, 2, 3])):
        code = f"x = '{name}'"
        (tmp_path / f"{name}.py").write_text(code)
        report = common | {
            "candidate_path": f"{name}.py",
            "candidate_sha256": digest(code.encode()),
            "latency_ms": latency,
        }
        (tmp_path / f"{name}.json").write_text(json.dumps(report))
    result = workspace.compare_reports("base.json", "candidate.json")
    assert result["comparable"] and result["median_ratio"] == 2
    report["workload"] = {"M": 64}
    (tmp_path / "candidate.json").write_text(json.dumps(report))
    assert not workspace.compare_reports("base.json", "candidate.json")["comparable"]
    (tmp_path / "base.py").write_text("modified")
    assert (
        "SHA-256"
        in workspace.compare_reports("base.json", "candidate.json")["reasons"][0]
    )
