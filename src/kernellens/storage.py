"""Transactional session/step records; no model credentials are persisted."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from kernellens.runtime.records import StepRecord
from kernellens.security import Redactor
from kernellens.tools.workspace import Workspace


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_dict(step: StepRecord) -> dict:
    action = step.action
    action_data = None
    if action:
        action_data = {"kind": action.kind, "reason": action.reason}
        if action.kind == "call_tool":
            action_data.update(
                tool_name=action.tool_name, arguments=dict(action.arguments)
            )
        elif action.kind == "finish":
            action_data["answer"] = action.answer
        else:
            action_data["question"] = action.question
    return {
        "decision": step.decision_number,
        "state": step.state_after.status.value,
        "action": action_data,
        "observation": {
            "status": step.observation.status.value,
            "content": step.observation.content,
        }
        if step.observation
        else None,
        "error": step.error,
    }


class Store:
    def __init__(self, workspace: Workspace, redact: Redactor):
        self.workspace, self.redact = workspace, redact
        workspace.internal_path("history.sqlite3-wal")
        workspace.internal_path("history.sqlite3-shm")
        self.connection = sqlite3.connect(
            workspace.internal_path("history.sqlite3"), timeout=5
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL, content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL,
                task_type TEXT NOT NULL, goal TEXT NOT NULL, summary TEXT,
                usage TEXT, pid INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS steps (
                run_id TEXT NOT NULL REFERENCES runs(id), decision INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(run_id, decision)
            );
            CREATE TABLE IF NOT EXISTS session_gpu (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id), profile TEXT NOT NULL
            );
        """)
        # Only orphaned processes are marked interrupted; live concurrent CLIs are untouched.
        for row in self.connection.execute(
            "SELECT id, pid FROM runs WHERE status='running'"
        ).fetchall():
            try:
                os.kill(row["pid"], 0)
            except ProcessLookupError:
                self.connection.execute(
                    "UPDATE runs SET status='interrupted', finished=? WHERE id=?",
                    (now(), row["id"]),
                )
            except PermissionError:
                pass
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_session(self, title: str = "新会话") -> str:
        session_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (session_id, now(), self.redact(title)[:100]),
            )
        return session_id

    def sessions(self) -> list[dict]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM sessions ORDER BY created DESC LIMIT 30"
            )
        ]

    def resolve_session(self, prefix: str) -> str:
        rows = [
            row["id"]
            for row in self.connection.execute("SELECT id FROM sessions")
            if row["id"].startswith(prefix)
        ]
        if not prefix or len(rows) != 1:
            raise ValueError("会话 ID 不存在或前缀不唯一；请用 /sessions 查看")
        return rows[0]

    def message(self, session_id: str, role: str, content: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, self.redact(content)),
            )

    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def gpu(self, session_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT profile FROM session_gpu WHERE session_id=?", (session_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set_gpu(self, session_id: str, profile: dict) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO session_gpu VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET profile=excluded.profile",
                (session_id, self.redact(json.dumps(profile, ensure_ascii=False))),
            )

    def request_gpu(self, run_id: str, question: str, reason: str) -> None:
        """Program input check uses decision 0 and consumes no model decision."""
        payload = {
            "decision": 0,
            "event": "gpu_required",
            "state": "waiting_input",
            "action": {"kind": "request_input", "question": question, "reason": reason},
            "observation": None,
            "error": None,
        }
        with self.connection:
            self.connection.execute(
                "INSERT INTO steps VALUES (?, 0, ?)",
                (run_id, self.redact(json.dumps(payload, ensure_ascii=False))),
            )

    def start_run(self, session_id: str, task_type: str, goal: str) -> str:
        run_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs(id,session_id,started,status,task_type,goal,pid) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    session_id,
                    now(),
                    "running",
                    task_type,
                    self.redact(goal),
                    os.getpid(),
                ),
            )
        return run_id

    def step(self, run_id: str, step: StepRecord) -> None:
        data = self.redact(json.dumps(record_dict(step), ensure_ascii=False))
        with self.connection:
            self.connection.execute(
                "INSERT INTO steps VALUES (?, ?, ?)",
                (run_id, step.decision_number, data),
            )

    def prefetch(self, run_id: str, observation) -> None:
        """Decision 0 is a program retrieval event, not a model budget decision."""
        action = observation.action
        payload = {
            "decision": 0,
            "event": "knowledge_prefetch",
            "state": "running",
            "action": {
                "kind": action.kind,
                "tool_name": action.tool_name,
                "arguments": dict(action.arguments),
                "reason": action.reason,
            },
            "observation": {
                "status": observation.status.value,
                "content": observation.content,
            },
            "error": None,
        }
        with self.connection:
            self.connection.execute(
                "INSERT INTO steps VALUES (?, 0, ?)",
                (run_id, self.redact(json.dumps(payload, ensure_ascii=False))),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        summary: str,
        usage: dict,
        evidence: list[dict],
        artifacts: dict,
        gpu: dict | None = None,
    ) -> str:
        directory = self.workspace.internal_path(f"runs/{run_id}")
        directory.mkdir(parents=True, exist_ok=True)
        report = self.redact(summary)
        self.workspace.internal_path(f"runs/{run_id}/report.md").write_text(
            report, encoding="utf-8"
        )
        details = {
            "run_id": run_id,
            "status": status,
            "usage": usage,
            "evidence": evidence,
            "artifacts": artifacts,
            "gpu": gpu,
        }
        self.workspace.internal_path(f"runs/{run_id}/result.json").write_text(
            self.redact(json.dumps(details, ensure_ascii=False, indent=2)),
            encoding="utf-8",
        )
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET status=?, finished=?, summary=?, usage=? WHERE id=?",
                (status, now(), report, json.dumps(usage), run_id),
            )
        return str(directory.relative_to(self.workspace.root) / "report.md")

    def runs(self, session_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT id,status,started,task_type,goal,summary,usage FROM runs WHERE session_id=? ORDER BY started DESC LIMIT 20",
                (session_id,),
            )
        ]

    def steps(self, run_id: str) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.connection.execute(
                "SELECT payload FROM steps WHERE run_id=? ORDER BY decision", (run_id,)
            )
        ]
