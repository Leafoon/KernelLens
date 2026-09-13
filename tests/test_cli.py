"""Exercise the actual CLI process and HTTP transport against a local provider."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def provider(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "body": data,
                    "auth": self.headers.get("Authorization"),
                    "path": self.path,
                }
            )
            if any(message["role"] == "tool" for message in data["messages"]):
                name, arguments = (
                    "finish",
                    {
                        "answer": "文件说明了 workspace-test [E1]。",
                        "reason": "已读文件",
                    },
                )
            else:
                name, arguments = "read_file", {"path": "notes.txt"}
            response = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "http-call",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            }
            raw = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env_file = tmp_path / "settings.env"
    env_file.write_text(
        f"base_url=http://127.0.0.1:{server.server_port}/v1\nmodel=test\napi_key=local-test-private-key\n"
    )
    try:
        yield env_file, requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def launch(env_file, arguments, stdin=""):
    # Keep user model credentials out of this local fixture's configuration.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "KERNELLENS_"))
        and key not in {"base_url", "api_key", "model", "BASE_URL", "API_KEY", "MODEL"}
    }
    return subprocess.run(
        [sys.executable, "-m", "kernellens", "--env-file", str(env_file), *arguments],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=30,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
    )


def test_interactive_workspace_selection_switch_and_persistence(tmp_path, provider):
    env_file, requests = provider
    first, second = tmp_path / "工作区 1", tmp_path / "workspace2"
    first.mkdir()
    second.mkdir()
    (first / "notes.txt").write_text("workspace-test")
    script = f"{tmp_path / 'missing'}\n{first}\n/diagnose 读取 notes.txt\n/history\n/runs\n/trace\n/workspace {second}\n/status\n/exit\n"
    result = launch(env_file, [], script)
    assert result.returncode == 0, result.stderr
    assert "工作区不可用" in result.stdout
    assert "workspace-test" in result.stdout and "completed" in result.stdout
    assert str(second) in result.stdout
    assert all(
        (root / ".kernellens/history.sqlite3").is_file() for root in (first, second)
    )
    assert len(requests) == 2
    assert requests[0]["auth"] == "Bearer local-test-private-key"
    assert requests[0]["path"] == "/v1/chat/completions"
    assert "local-test-private-key" not in result.stdout + result.stderr


def test_one_shot_json_and_resume(tmp_path, provider):
    env_file, _ = provider
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("workspace-test")
    first = launch(env_file, ["-w", str(workspace), "-p", "读取 notes.txt", "--json"])
    assert first.returncode == 0, first.stderr
    data = json.loads(first.stdout)
    assert data["status"] == "completed"
    assert (workspace / data["report_path"]).is_file()
    resumed = launch(
        env_file,
        [
            "-w",
            str(workspace),
            "--resume",
            data["session_id"],
            "-p",
            "再核对一次 notes.txt",
            "--json",
        ],
    )
    assert resumed.returncode == 0
    assert json.loads(resumed.stdout)["session_id"] == data["session_id"]


def test_missing_config_and_invalid_workspace_are_readable(tmp_path):
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    failed = launch(env_file, ["-w", str(tmp_path), "-p", "hello", "--json"])
    assert failed.returncode == 1
    assert "api_key" in json.loads(failed.stdout)["error"]
    assert "Traceback" not in failed.stderr
    invalid = launch(env_file, ["-w", str(tmp_path / "missing"), "-p", "hello"])
    assert invalid.returncode == 1
    assert "已存在的目录" in invalid.stdout


def test_workspace_selection_can_quit_without_api(tmp_path):
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    result = launch(env_file, [], "q\n")
    assert result.returncode == 0
    assert "workspace>" in result.stdout


def test_gpu_one_shot_wait_and_resume(tmp_path, provider):
    env_file, requests = provider
    workspace = tmp_path / "gpu-workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("workspace-test")
    first = launch(
        env_file,
        [
            "-w",
            str(workspace),
            "--task",
            "diagnose",
            "-p",
            "诊断编译报错，读取 notes.txt",
            "--json",
        ],
    )
    assert first.returncode == 2
    data = json.loads(first.stdout)
    assert data["status"] == "waiting_input" and not requests
    resumed = launch(
        env_file,
        [
            "-w",
            str(workspace),
            "--resume",
            data["session_id"],
            "--task",
            "diagnose",
            "-p",
            "NVIDIA A100",
            "--json",
        ],
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    data = json.loads(resumed.stdout)
    assert data["gpu"]["model"] == "NVIDIA A100"
    assert "诊断编译报错" in json.dumps(requests[0]["body"], ensure_ascii=False)


def test_gpu_commands_and_cli_override_on_resume(tmp_path, provider):
    env_file, requests = provider
    (tmp_path / "notes.txt").write_text("workspace-test")
    first = launch(
        env_file,
        ["-w", str(tmp_path), "--gpu", "A100", "-p", "读取 notes.txt", "--json"],
    )
    data = json.loads(first.stdout)
    assert data["gpu"]["model"] == "A100"
    second = launch(
        env_file,
        [
            "-w",
            str(tmp_path),
            "--resume",
            data["session_id"],
            "--gpu",
            "AMD MI300X",
            "-p",
            "读取 notes.txt",
            "--json",
        ],
    )
    assert json.loads(second.stdout)["gpu"]["backend"] == "hip"
    count = len(requests)
    interactive = launch(
        env_file,
        ["-w", str(tmp_path)],
        "/gpu RTX 4090\n/status\n/new\n/gpu\n/gpu Apple M4\n/gpu clear\n/generate 生成 GEMM\n/trace\n/exit\n",
    )
    assert interactive.returncode == 0
    assert '"model": "RTX 4090"' in interactive.stdout
    assert "目标 GPU: 未提供" in interactive.stdout
    assert (
        "waiting_input" in interactive.stdout and "gpu_required" in interactive.stdout
    )
    assert len(requests) == count
