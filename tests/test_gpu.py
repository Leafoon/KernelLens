"""GPU intake, real session recovery, and retrieval filtering without paid calls."""

import json

import pytest

from kernellens.application import AgentApplication, infer_task
from kernellens.config import Settings, load_settings
from kernellens.domain.task import TaskType
from kernellens.gpu import gpu_from_text, gpu_profile
from kernellens.knowledge import bundled_knowledge_dir
from kernellens.tools.workspace import Workspace


def reply(name, arguments):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "gpu-test",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        },
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def configured(**kwargs):
    return Settings(
        base_url="https://example.org/v1",
        api_key="fixture-key",
        model="fixture",
        **kwargs,
    )


@pytest.mark.parametrize(
    "text,model,backend",
    [
        ("生成 GEMM，目标 NVIDIA A100", "NVIDIA A100", "cuda"),
        ("RTX4090", "RTX4090", "cuda"),
        ("我用 AMD MI300X，生成算子", "AMD MI300X", "hip"),
        ("目标GPU是 Apple M4 Max", "Apple M4 Max", "metal"),
        ("本机 Apple M4，目标 A100 80GB", "A100 80GB", "cuda"),
        ("本机 GPU 是 Apple M4，目标 GPU 是 A100", "A100", "cuda"),
        ("GPU: CustomChip X1", "CustomChip X1", ""),
        ("目标 GPU：CUDA", "", ""),
        ("目标 GPU 是 A100 或 H100", "", ""),
        ("目标 GPU：不知道", "", ""),
        (
            "测试目标是 NVIDIA A100/SM80（只是假设的验收目标，没有真实 GPU）",
            "NVIDIA A100",
            "cuda",
        ),
    ],
)
def test_declared_gpu(text, model, backend):
    profile = gpu_from_text(text, allow_mentions=True)
    assert profile is not None
    assert (profile.model, profile.backend) == (model, backend)


@pytest.mark.parametrize(
    "text",
    [
        "生成 GEMM，M=N=K=128",
        "本机是 Apple M4，生成一个算子",
        "本机 GPU 是 Apple M4，生成一个算子",
        "我的目标是生成算子",
        "读取 H100.py",
        "不使用 A100",
        "例如 A100",
    ],
)
def test_no_invented_execution_device(text):
    profile = gpu_from_text(text, allow_mentions=True)
    assert profile is None or not profile.model


def test_concept_mentions_do_not_change_session_target():
    assert gpu_from_text("解释 A100 与 H100 的区别", allow_mentions=False) is None
    assert gpu_from_text("RTX 4090", allow_mentions=False).backend == "cuda"
    assert not gpu_profile("A100 或 H100").model


@pytest.mark.parametrize(
    "goal", ["生成 GEMM", "帮我实现矩阵乘法", "优化 baseline.py", "诊断编译报错"]
)
def test_missing_gpu_waits_without_model_config_or_tools(tmp_path, goal):
    app = AgentApplication(
        Workspace(tmp_path),
        Settings(),
        transport=lambda *_: pytest.fail("must not request"),
    )
    try:
        result = app.run(app.store.create_session(), goal)
        assert result.status == "waiting_input"
        assert result.usage["http_requests"] == result.usage["total_tokens"] == 0
        assert not result.artifacts
        assert "GPU 型号" in result.answer
        assert app.store.steps(result.run_id)[0]["event"] == "gpu_required"
        assert (
            json.loads(
                (tmp_path / result.report_path).with_name("result.json").read_text()
            )["gpu"]["model"]
            == ""
        )
    finally:
        app.close()


def test_reply_after_restart_preserves_goal_and_persists_gpu(tmp_path):
    app = AgentApplication(Workspace(tmp_path), Settings())
    session = app.store.create_session()
    result = app.run(session, "生成 GEMM，M=N=K=128，A/B/C float16")
    assert result.status == "waiting_input"
    app.close()
    payloads = []

    def transport(payload, timeout):
        payloads.append(payload)
        return reply(
            "request_input", {"question": "请指定输出路径", "reason": "测试后续澄清"}
        )

    app = AgentApplication(
        Workspace(tmp_path), configured(), transport=transport, emit=lambda _: None
    )
    try:
        result = app.run(session, "NVIDIA A100 80GB", TaskType.GENERATE)
        assert len(payloads) == 1
        assert "M=N=K=128" in json.dumps(payloads[0], ensure_ascii=False)
        assert result.gpu["model"] == "NVIDIA A100 80GB"
        assert result.gpu["backend"] == "cuda"
        # A second non-device answer retains GPU and the original constraints.
        app.run(session, "artifacts/gemm.py")
        assert len(payloads) == 2
        assert '"model": "NVIDIA A100 80GB"' in payloads[1]["messages"][0]["content"]
        assert app.store.runs(session)[0]["task_type"] == "generate"
        # New sessions do not inherit a device chosen in another session.
        assert not app.gpu(app.store.create_session()).model
    finally:
        app.close()


def test_session_override_clear_and_unknown_model(tmp_path):
    app = AgentApplication(
        Workspace(tmp_path),
        configured(gpu="A100"),
        emit=lambda _: None,
        transport=lambda *_: reply(
            "request_input", {"question": "路径？", "reason": "补充"}
        ),
    )
    try:
        session = app.store.create_session()
        assert app.gpu(session).model == "A100"
        app.set_gpu(session, "H100")
        result = app.run(session, "生成 GEMM，目标 AMD MI300X")
        assert result.gpu["backend"] == "hip"
        app.set_gpu(session, "")
        result = app.run(session, "继续")
        assert result.status == "waiting_input" and result.usage["http_requests"] == 0
        assert not result.gpu["model"]  # Old goal's MI300X must not undo clear.
        app.set_gpu(session, "CustomChip X1")
        assert app.gpu(session).model == "CustomChip X1"
        assert app.gpu(session).backend == ""
    finally:
        app.close()


@pytest.mark.parametrize(
    "model,backend", [("A100", "cuda"), ("AMD MI300X", "hip"), ("Apple M4", "metal")]
)
def test_gpu_reaches_prefetch_followup_search_and_report(tmp_path, model, backend):
    replies = iter(
        [
            reply("search_knowledge", {"query": "T.copy", "top_k": 2}),
            reply(
                "finish", {"answer": "仅解释源码；GPU 未执行 [E1]", "reason": "完成"}
            ),
        ]
    )
    payloads = []

    def transport(payload, timeout):
        payloads.append(payload)
        return next(replies)

    app = AgentApplication(
        Workspace(tmp_path),
        configured(gpu=model, knowledge_dir=str(bundled_knowledge_dir())),
        transport=transport,
        emit=lambda _: None,
    )
    seen = []
    search = app.knowledge.search

    def capture(**kwargs):
        result = search(**kwargs)
        seen.append((kwargs, result))
        return result

    app.knowledge.search = capture
    try:
        result = app.run(app.store.create_session(), "解释 T.copy 的参数")
        assert result.status == "completed"
        assert len(seen) == 2
        assert all(kwargs["target"] == backend for kwargs, _ in seen)
        assert model in seen[0][0]["query"]
        assert all(
            not unit["targets"] or backend in unit["targets"]
            for _, data in seen
            for unit in data.get("results", [])
        )
        assert model in payloads[0]["messages"][0]["content"]
        report = json.loads(
            (tmp_path / result.report_path).with_name("result.json").read_text()
        )
        assert report["gpu"] == result.gpu
    finally:
        app.close()


def test_gpu_config_priority_and_input_bounds(tmp_path):
    env = tmp_path / "config.env"
    env.write_text('KERNELLENS_GPU="A100"\n')
    assert load_settings({}, env_file=env).gpu == "A100"
    assert load_settings({"KERNELLENS_GPU": "H100"}, env_file=env).gpu == "H100"
    assert (
        load_settings(
            {"KERNELLENS_GPU": "H100"}, env_file=env, overrides={"gpu": "RTX 4090"}
        ).gpu
        == "RTX 4090"
    )
    for invalid in ["A100\nH100", "x" * 161]:
        with pytest.raises(ValueError):
            gpu_profile(invalid)
    assert infer_task("帮我实现矩阵乘法") is TaskType.GENERATE
