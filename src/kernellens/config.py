"""Configuration stays independent of the selected task workspace."""

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from kernellens.gpu import gpu_profile
from kernellens.knowledge import bundled_knowledge_dir


class ConfigurationError(ValueError):
    pass


def read_env(path: Path) -> dict[str, str]:
    """Read literal dotenv values; do not execute shell or expand variables."""
    result = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"无法读取配置文件: {path}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(.*)", line)
        if not match:
            raise ConfigurationError(f".env 第 {number} 行格式错误，需要 KEY=value")
        try:
            tokens = shlex.split(match[2], comments=True, posix=True)
        except ValueError as exc:
            raise ConfigurationError(f".env 第 {number} 行引号未闭合") from exc
        result[match[1]] = " ".join(tokens)
    return result


def find_env(start: Path) -> Path | None:
    for directory in (start.resolve(), *start.resolve().parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    candidate = Path(__file__).resolve().parents[2] / ".env"
    return candidate if candidate.is_file() else None


@dataclass(frozen=True)
class Settings:
    log_level: str = "INFO"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    max_decisions: int = 20
    timeout: float = 60.0
    max_run_seconds: float = 300.0
    max_output_tokens: int = 4096
    max_total_tokens: int = 60000
    context_chars: int = 48000
    max_retries: int = 2
    tool_mode: str = "native"
    knowledge_dir: str = ""
    gpu: str = ""

    def require_model(self) -> None:
        missing = [
            name for name in ("base_url", "api_key", "model") if not getattr(self, name)
        ]
        if missing:
            raise ConfigurationError(
                "缺少模型配置: " + ", ".join(missing) + "；请设置 .env 或环境变量"
            )

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return (
            base if base.endswith("/chat/completions") else base + "/chat/completions"
        )


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    env_file: Path | None = None,
    overrides: Mapping[str, object] | None = None,
) -> Settings:
    env = os.environ if environ is None else environ
    file_values = read_env(env_file) if env_file else {}
    explicit = overrides or {}

    def value(name: str, default: object) -> str:
        aliases = ["KERNELLENS_" + name.upper(), name, name.upper()]
        if name in {"base_url", "api_key", "model"}:
            aliases.insert(1, "OPENAI_" + name.upper())
        if name in explicit and explicit[name] is not None:
            return str(explicit[name])
        for layer in (env, file_values):
            for alias in aliases:
                if alias in layer:
                    return layer[alias].strip()
        return str(default)

    level = value("log_level", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError(
            "KERNELLENS_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
        )
    numbers = {}
    for name, default, low, high, cast in (
        ("max_decisions", 20, 1, 200, int),
        ("timeout", 60, 1, 600, float),
        ("max_run_seconds", 300, 1, 3600, float),
        ("max_output_tokens", 4096, 128, 32768, int),
        ("max_total_tokens", 60000, 128, 1000000, int),
        ("context_chars", 48000, 8000, 500000, int),
        ("max_retries", 2, 0, 5, int),
    ):
        try:
            parsed = cast(value(name, default))
            if not low <= parsed <= high:
                raise ValueError
        except ValueError as exc:
            raise ConfigurationError(f"{name} 必须在 {low}..{high} 范围内") from exc
        numbers[name] = parsed
    base = value("base_url", "").rstrip("/")
    if base:
        try:
            url = urlsplit(base)
            valid = (
                url.scheme in {"https", "http"}
                and url.hostname
                and not (url.username or url.password or url.query or url.fragment)
            )
            valid = valid and (
                url.scheme == "https"
                or url.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise ConfigurationError(
                "base_url 需要 HTTPS API 地址（本机测试允许 HTTP），不能包含凭证、query 或 fragment"
            )
    mode = value("tool_mode", "native")
    if mode not in {"native", "json"}:
        raise ConfigurationError("tool_mode 必须为 native 或 json")
    return Settings(
        log_level=level,
        base_url=base,
        api_key=value("api_key", ""),
        model=value("model", ""),
        tool_mode=mode,
        knowledge_dir=value("knowledge_dir", bundled_knowledge_dir()),
        gpu=gpu_profile(value("gpu", "")).model,
        **numbers,
    )
