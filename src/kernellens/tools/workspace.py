"""Bounded local file operations. No imports or execution of user code."""

import ast
import fnmatch
import hashlib
import json
import math
import os
import stat
import statistics
import tempfile
from pathlib import Path


class WorkspaceError(ValueError):
    pass


MAX_FILE_BYTES = 1_000_000
PRIVATE_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".kernellens",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sensitive(path: Path) -> bool:
    for part in path.parts:
        name = part.lower()
        if (
            name in PRIVATE_PARTS
            or name.startswith(".env")
            or name
            in {
                "credentials",
                "credentials.json",
                "secrets.json",
                "secrets.yaml",
                "id_rsa",
                "id_ed25519",
            }
            or name.endswith((".pem", ".key", ".p12", ".pfx"))
        ):
            return True
    return False


class Workspace:
    def __init__(self, path: str | Path):
        self.root = Path(path).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkspaceError("工作区必须是已存在的目录")
        self.internal = self.root / ".kernellens"
        if self.internal.is_symlink():
            raise WorkspaceError(".kernellens 不能是符号链接")
        self.internal.mkdir(mode=0o700, exist_ok=True)

    def internal_path(self, relative: str) -> Path:
        path = self.internal / relative
        resolved = path.resolve()
        if not resolved.is_relative_to(self.internal.resolve()):
            raise WorkspaceError("内部产物路径越界")
        current = self.internal
        for part in path.relative_to(self.internal).parts:
            current /= part
            if current.is_symlink():
                raise WorkspaceError("内部产物路径不能是符号链接")
        return path

    def resolve(self, name: str) -> Path:
        path = Path(name)
        unresolved = path if path.is_absolute() else self.root / path
        try:
            lexical = unresolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("路径不属于当前工作区") from exc
        if sensitive(lexical):
            raise WorkspaceError("路径属于凭证、内部记录或被排除的目录")
        current = self.root
        for part in lexical.parts:
            current /= part
            if current.is_symlink():
                raise WorkspaceError("工具不跟随符号链接")
        resolved = unresolved.resolve()
        if not resolved.is_relative_to(self.root) or sensitive(
            resolved.relative_to(self.root)
        ):
            raise WorkspaceError("路径越出工作区或访问受限目录")
        return resolved

    def read_bytes(self, name: str) -> tuple[Path, bytes]:
        path = self.resolve(name)
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise WorkspaceError("只允许读取普通文件")
                if info.st_size > MAX_FILE_BYTES:
                    raise WorkspaceError("文件超过 1 MB 上限；请先拆分材料")
                data = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise WorkspaceError(f"无法读取文件: {type(exc).__name__}") from exc
        if len(data) > MAX_FILE_BYTES or b"\x00" in data:
            raise WorkspaceError("文件过大或为二进制内容")
        return path, data

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 200) -> dict:
        file, data = self.read_bytes(path)
        lines = data.decode("utf-8").splitlines()
        chosen = lines[start_line - 1 : start_line - 1 + max_lines]
        content = "\n".join(f"{i}: {line}" for i, line in enumerate(chosen, start_line))
        return {
            "path": str(file.relative_to(self.root)),
            "sha256": digest(data),
            "total_lines": len(lines),
            "start_line": start_line,
            "content": content[:16000],
            "truncated": len(content) > 16000
            or start_line - 1 + len(chosen) < len(lines),
        }

    def files(self, path: str, pattern: str):
        directory = self.resolve(path)
        if not directory.is_dir():
            raise WorkspaceError("path 必须是目录")
        scanned = 0
        for parent, dirs, files in os.walk(directory, followlinks=False):
            scanned += 1
            if scanned > 10000:
                return
            dirs[:] = sorted(
                d
                for d in dirs
                if not sensitive(Path(d)) and not (Path(parent) / d).is_symlink()
            )
            for name in sorted(files):
                scanned += 1
                if scanned > 10000:
                    return
                file = Path(parent) / name
                relative = file.relative_to(self.root)
                if file.is_symlink() or sensitive(relative):
                    continue
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(
                    str(relative), pattern
                ):
                    yield str(relative)

    def list_files(self, path: str = ".", pattern: str = "*", limit: int = 100) -> dict:
        found = []
        for name in self.files(path, pattern):
            found.append(name)
            if len(found) > limit:
                break
        return {
            "files": found[:limit],
            "truncated": len(found) > limit,
            "scan_limit": 10000,
        }

    def search_text(
        self, query: str, path: str = ".", pattern: str = "*", limit: int = 100
    ) -> dict:
        matches, scanned = [], 0
        for name in self.files(path, pattern):
            scanned += 1
            if scanned > 300:
                break
            try:
                _, data = self.read_bytes(name)
                lines = data.decode("utf-8").splitlines()
            except (WorkspaceError, UnicodeError):
                continue
            for number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    matches.append(
                        {
                            "path": name,
                            "line": number,
                            "text": line[:500],
                            "sha256": digest(data),
                        }
                    )
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True}
        return {
            "matches": matches,
            "truncated": scanned > 300,
            "scanned_files": min(scanned, 300),
        }

    def write_file(
        self, path: str, content: str, expected_sha256: str = "", *, run_id: str
    ) -> dict:
        file = self.resolve(path)
        if not file.name or file == self.root:
            raise WorkspaceError("需要文件路径")
        data = content.encode("utf-8")
        if len(data) > 200000:
            raise WorkspaceError("写入超过 200 KB 上限")
        previous = None
        if file.exists():
            _, previous = self.read_bytes(path)
            if not expected_sha256 or digest(previous) != expected_sha256:
                raise WorkspaceError(
                    "文件已存在或已改变；请先 read_file 并提供正确 expected_sha256"
                )
        elif expected_sha256:
            raise WorkspaceError("文件已不存在；不能覆盖读取时的版本")
        file.parent.mkdir(parents=True, exist_ok=True)
        # Check newly created parent paths again before placing the atomic replacement.
        self.resolve(path)
        backup = None
        if previous is not None:
            backup = self.internal_path(f"runs/{run_id}/backups/{digest(previous)}.bak")
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_bytes(previous)
        fd, temp_name = tempfile.mkstemp(prefix=".kernellens-write-", dir=file.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if previous is None:
                # link refuses an intervening file creation; unlike replace it cannot clobber.
                os.link(temp_name, file)
            else:
                _, current = self.read_bytes(path)
                if digest(current) != expected_sha256:
                    raise WorkspaceError("写入前文件已改变，请重新读取")
                os.replace(temp_name, file)
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return {
            "path": str(file.relative_to(self.root)),
            "sha256": digest(data),
            "bytes": len(data),
            "backup": str(backup.relative_to(self.root)) if backup else None,
        }

    def check_python(self, path: str) -> dict:
        file, data = self.read_bytes(path)
        result = {
            "path": str(file.relative_to(self.root)),
            "sha256": digest(data),
            "compilation": "not_run",
            "correctness": "not_run",
            "performance": "not_run",
        }
        try:
            tree = ast.parse(
                data.decode("utf-8"), filename=str(file.relative_to(self.root))
            )
        except SyntaxError as exc:
            return {
                **result,
                "syntax": "failed",
                "line": exc.lineno,
                "message": exc.msg,
            }
        imports = sorted(
            {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
        )
        return {
            **result,
            "syntax": "passed",
            "imports": imports,
            "api_evidence": "not_run",
        }

    def read_report(self, path: str) -> dict:
        file, data = self.read_bytes(path)
        report = json.loads(data)
        if not isinstance(report, dict):
            raise WorkspaceError("报告必须是 JSON 对象")
        # A matching artifact does not authenticate the report provider or hardware.
        candidate = report.get("candidate_path")
        expected = report.get("candidate_sha256")
        associated = False
        if isinstance(candidate, str) and isinstance(expected, str):
            _, code = self.read_bytes(candidate)
            associated = digest(code) == expected
        return {
            "path": str(file.relative_to(self.root)),
            "sha256": digest(data),
            "source": "user_report",
            "candidate_matches": associated,
            "report": report,
            "notice": "报告由用户提供；候选匹配不认证硬件执行，性能比较还需一致环境、工作负载与 baseline。",
        }

    def compare_reports(self, baseline_path: str, candidate_path: str) -> dict:
        baseline = self.read_report(baseline_path)
        candidate = self.read_report(candidate_path)
        reasons = []
        reports = (baseline["report"], candidate["report"])
        if not baseline["candidate_matches"] or not candidate["candidate_matches"]:
            reasons.append("报告中的代码 SHA-256 与当前文件不匹配")
        for field in ("environment", "workload", "measurement"):
            if not all(
                isinstance(report.get(field), dict) and report[field]
                for report in reports
            ) or reports[0].get(field) != reports[1].get(field):
                reasons.append(f"{field} 缺失或不一致")
        for report in reports:
            if (
                not isinstance(report.get("checks"), dict)
                or report["checks"].get("correctness") != "passed"
            ):
                reasons.append("两份报告都需要明确记录 correctness=passed")
                break
        samples = [report.get("latency_ms") for report in reports]
        if not all(
            isinstance(items, list)
            and len(items) >= 3
            and all(
                type(item) in (int, float) and math.isfinite(item) and item > 0
                for item in items
            )
            for items in samples
        ):
            reasons.append("latency_ms 需要至少三个正的有限数值样本")
        result = {
            "source": "user_report",
            "baseline": baseline_path,
            "candidate": candidate_path,
            "comparable": not reasons,
            "reasons": reasons,
            "notice": "仅描述用户报告中可比样本的中位数比值；不认证执行来源，不证明统计显著性。",
        }
        if not reasons:
            before, after = (statistics.median(items) for items in samples)
            result.update(
                baseline_median_ms=before,
                candidate_median_ms=after,
                median_ratio=before / after,
            )
        return result
