import pytest

from kernellens.config import load_settings


def test_explicit_empty_environment_uses_default(monkeypatch):
    monkeypatch.setenv("KERNELLENS_LOG_LEVEL", "ERROR")

    assert load_settings({}).log_level == "INFO"


def test_loads_and_normalizes_process_environment(monkeypatch):
    monkeypatch.setenv("KERNELLENS_LOG_LEVEL", " debug ")

    assert load_settings().log_level == "DEBUG"


@pytest.mark.parametrize("value", ["", "verbose"])
def test_rejects_invalid_log_level(value):
    with pytest.raises(ValueError, match="KERNELLENS_LOG_LEVEL"):
        load_settings({"KERNELLENS_LOG_LEVEL": value})
