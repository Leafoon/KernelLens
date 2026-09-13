import pytest

from kernellens.config import ConfigurationError, load_settings, read_env


def test_dotenv_lowercase_and_layer_precedence(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        'base_url="https://example.org/v1"\nmodel=example\napi_key="secret#literal" # comment\n'
    )
    settings = load_settings({"OPENAI_MODEL": "process"}, env_file=env)
    assert settings.model == "process"
    assert settings.api_key == "secret#literal"
    assert "secret#literal" not in repr(settings)
    assert settings.endpoint == "https://example.org/v1/chat/completions"
    assert load_settings({}, env_file=env, overrides={"model": "cli"}).model == "cli"


@pytest.mark.parametrize(
    "key,value",
    [
        ("base_url", "http://example.org/v1"),
        ("base_url", "https://user:pass@example.org"),
        ("max_decisions", "true"),
        ("timeout", "nan"),
        ("max_retries", "-1"),
        ("tool_mode", "other"),
    ],
)
def test_bad_settings_have_actionable_errors(key, value):
    with pytest.raises(ConfigurationError):
        load_settings({key: value})


def test_missing_config_is_only_required_for_model_use():
    settings = load_settings({})
    with pytest.raises(ConfigurationError, match="api_key"):
        settings.require_model()


def test_dotenv_never_executes_shell(tmp_path):
    env = tmp_path / ".env"
    env.write_text("api_key='$(touch should-not-exist)'\n")
    assert read_env(env)["api_key"].startswith("$(touch")
    assert not (tmp_path / "should-not-exist").exists()
