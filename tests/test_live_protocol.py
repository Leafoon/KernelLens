import io
import json
import time
import urllib.error
from dataclasses import replace

import pytest

from kernellens.application import AgentApplication
from kernellens.config import Settings
from kernellens.domain.task import TaskType
from kernellens.models.client import ChatClient, ModelError, ResourceLimit
from kernellens.tools.workspace import Workspace


def response(name, arguments, call_id="call-1"):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
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
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def settings(**kw):
    return replace(
        Settings(
            base_url="https://example.org/v1",
            api_key="private-key",
            model="test",
            max_retries=0,
        ),
        **kw,
    )


class ScriptedTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.payloads = []

    def __call__(self, payload, timeout):
        self.payloads.append(payload)
        result = next(self.replies)
        if isinstance(result, BaseException):
            raise result
        return result


def test_native_tool_loop_and_protocol_ids(tmp_path):
    (tmp_path / "notes.txt").write_text("facts")
    transport = ScriptedTransport(
        [
            response("read_file", {"path": "notes.txt"}, "read-123"),
            response("finish", {"answer": "已读取 facts [E1]", "reason": "完成"}),
        ]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    session = app.store.create_session()
    result = app.run(session, "读取 notes.txt")
    assert result.status == "completed"
    assert result.usage["total_tokens"] == 30
    tool_messages = [
        item for item in transport.payloads[1]["messages"] if item["role"] == "tool"
    ]
    assert tool_messages[0]["tool_call_id"] == "read-123"
    assert "facts" in tool_messages[0]["content"]
    assert len(app.store.steps(result.run_id)) == 2
    assert (tmp_path / result.report_path).is_file()
    app.close()


@pytest.mark.parametrize("task_type", [TaskType.GENERATE, TaskType.OPTIMIZE])
def test_code_delivery_requires_current_syntax_and_baseline(tmp_path, task_type):
    (tmp_path / "baseline.py").write_text("x = 1\n")
    replies = [
        response("finish", {"answer": "完成", "reason": "提前提交"}, "premature")
    ]
    if task_type is TaskType.OPTIMIZE:
        replies.append(response("read_file", {"path": "baseline.py"}, "baseline"))
    replies += [
        response(
            "write_file",
            {"path": "artifacts/candidate.py", "content": "x = 2\n"},
            "write",
        ),
        response("check_python", {"path": "artifacts/candidate.py"}, "check"),
        response(
            "finish",
            {"answer": "候选已保存 [E1]；GPU 未运行。", "reason": "完成"},
            "done",
        ),
    ]
    transport = ScriptedTransport(replies)
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    result = app.run(app.store.create_session(), "按要求交付候选，目标 A100", task_type)
    assert result.status == "completed"
    assert "not_run" not in (tmp_path / "artifacts/candidate.py").read_text()
    assert "交付审核未通过" in json.dumps(transport.payloads[1], ensure_ascii=False)
    assert app.store.steps(result.run_id)[0]["error"].startswith("FinishRejected")
    assert "AST 语法：passed" in result.answer
    app.close()


def test_waiting_input_continues_same_session_after_restart(tmp_path):
    transport = ScriptedTransport(
        [response("request_input", {"question": "目标设备？", "reason": "缺少信息"})]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    session = app.store.create_session()
    result = app.run(session, "解释目标设备", TaskType.DIAGNOSE)
    assert result.status == "waiting_input"
    app.close()
    next_transport = ScriptedTransport(
        [response("finish", {"answer": "收到设备信息", "reason": "回答完毕"})]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=next_transport
    )
    result = app.run(session, "NVIDIA A100")
    assert result.status == "completed"
    assert "目标设备" in json.dumps(next_transport.payloads[0], ensure_ascii=False)
    assert len(app.store.runs(session)) == 2
    app.close()


def test_invalid_tool_arguments_can_be_corrected_within_budget(tmp_path):
    (tmp_path / "x.txt").write_text("x")
    transport = ScriptedTransport(
        [
            response("read_file", {"path": True}, "bad"),
            response("read_file", {"path": "x.txt"}, "good"),
            response("finish", {"answer": "读取 x [E1]", "reason": "完成"}),
        ]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    result = app.run(app.store.create_session(), "读取文件")
    assert result.status == "completed"
    assert "invalid_arguments" in json.dumps(transport.payloads[1])
    app.close()


def test_malformed_action_uses_budget_instead_of_unbounded_retry(tmp_path):
    broken = response("read_file", {})
    broken["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
        "{not-json"
    )
    app = AgentApplication(
        Workspace(tmp_path),
        settings(max_decisions=2),
        emit=lambda _: None,
        transport=ScriptedTransport([broken, broken]),
    )
    result = app.run(app.store.create_session(), "读取文件")
    assert result.status == "budget_exhausted"
    assert len(app.store.steps(result.run_id)) == 2
    app.close()


@pytest.mark.parametrize(
    "error,status",
    [
        (KeyboardInterrupt(), "interrupted"),
        (urllib.error.URLError("private-key"), "failed"),
    ],
)
def test_failure_preserves_prior_writes_and_redacts_errors(tmp_path, error, status):
    transport = ScriptedTransport(
        [response("write_file", {"path": "kept.txt", "content": "saved"}), error]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    session = app.store.create_session()
    result = app.run(session, "保存文件")
    assert result.status == status
    assert (tmp_path / "kept.txt").read_text() == "saved"
    assert "private-key" not in result.answer
    assert result.usage["total_tokens"] is None
    assert app.store.runs(session)[0]["status"] == status
    app.close()


def test_http_errors_retry_only_retryable_codes(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    transport = ScriptedTransport(
        [
            urllib.error.HTTPError(
                "https://example.org",
                429,
                "private-key",
                {},
                io.BytesIO(b"private-key"),
            ),
            response("finish", {"answer": "ok", "reason": "done"}),
        ]
    )
    client = ChatClient(settings(max_retries=1), transport=transport)
    assert client.complete([], [])["tool_calls"]
    assert client.requests == 2
    denied = ChatClient(
        settings(max_retries=2),
        transport=ScriptedTransport(
            [
                urllib.error.HTTPError(
                    "https://example.org", 401, "private-key", {}, None
                )
            ]
        ),
    )
    with pytest.raises(ModelError, match="401") as error:
        denied.complete([], [])
    assert "private-key" not in str(error.value) and denied.requests == 1


def test_deadline_prevents_request():
    client = ChatClient(
        settings(), transport=lambda *_: pytest.fail("must not request")
    )
    client.deadline = 0
    with pytest.raises(ResourceLimit):
        client.complete([], [])


def test_json_protocol_reaches_same_tools(tmp_path):
    payloads = [
        dict(
            kind="call_tool",
            tool_name="write_file",
            arguments={"path": "note.txt", "content": "hello"},
            reason="save",
        ),
        dict(kind="finish", answer="saved [E1]", reason="done"),
    ]
    replies = [
        {
            "choices": [
                {"message": {"role": "assistant", "content": json.dumps(payload)}}
            ]
        }
        for payload in payloads
    ]
    transport = ScriptedTransport(replies)
    app = AgentApplication(
        Workspace(tmp_path),
        settings(tool_mode="json"),
        emit=lambda _: None,
        transport=transport,
    )
    result = app.run(app.store.create_session(), "保存笔记")
    assert result.status == "completed"
    assert "tools" not in transport.payloads[0]
    assert result.usage["total_tokens"] is None
    app.close()


def test_dtype_rejection_then_correction_allows_helper_script(tmp_path):
    from kernellens.tools.workspace import digest

    wrong = 'def kernel(C: T.Tensor((128, 128), "float32")):\n    pass\n'
    correct = wrong.replace('"float32"', '"float16"')
    transport = ScriptedTransport(
        [
            response("write_file", {"path": "kernel.py", "content": wrong}),
            response("check_python", {"path": "kernel.py"}),
            response("finish", {"answer": "交付 [E1]", "reason": "尝试交付"}),
            response(
                "write_file",
                {
                    "path": "kernel.py",
                    "content": correct,
                    "expected_sha256": digest(wrong.encode()),
                },
            ),
            response("check_python", {"path": "kernel.py"}),
            response(
                "write_file",
                {
                    "path": "test_kernel.py",
                    "content": "# Server test scaffold, never executed by Agent.\n",
                },
            ),
            response("check_python", {"path": "test_kernel.py"}),
            response(
                "finish",
                {"answer": "已修正输出声明 [E4]，GPU 未执行。", "reason": "交付"},
            ),
        ]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    result = app.run(
        app.store.create_session(), "生成 GEMM，C float16，目标 A100", TaskType.GENERATE
    )
    assert result.status == "completed"
    assert (tmp_path / "kernel.py").read_text() == correct
    assert "shape/dtype" in app.store.steps(result.run_id)[2]["error"]
    assert "交付审核未通过" in json.dumps(transport.payloads[3], ensure_ascii=False)
    app.close()


def test_402_provider_detail_is_redacted_and_not_retried():
    body = json.dumps(
        {"error": {"message": "Account private-key has no credit"}}
    ).encode()
    client = ChatClient(
        settings(max_retries=2),
        transport=ScriptedTransport(
            [
                urllib.error.HTTPError(
                    "https://example.org", 402, "Payment", {}, io.BytesIO(body)
                )
            ]
        ),
    )
    with pytest.raises(ModelError, match="402") as error:
        client.complete([], [])
    assert "has no credit" in str(error.value)
    assert "private-key" not in str(error.value)
    assert client.requests == 1
    assert not client.usage()["usage_complete"]


def test_nonstring_native_arguments_receive_protocol_feedback(tmp_path):
    malformed = response("read_file", {})
    malformed["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = {}
    transport = ScriptedTransport(
        [malformed, response("finish", {"answer": "参数错误已处理", "reason": "完成"})]
    )
    app = AgentApplication(
        Workspace(tmp_path), settings(), emit=lambda _: None, transport=transport
    )
    result = app.run(app.store.create_session(), "解释工具输入")
    assert result.status == "completed"
    assert "JSON 字符串" in json.dumps(transport.payloads[1], ensure_ascii=False)
    app.close()
