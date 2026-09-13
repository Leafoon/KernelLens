"""Source-backed TileLang knowledge; importing this package never imports TileLang."""

from pathlib import Path


def bundled_knowledge_dir() -> Path:
    """Resolve package data independently of cwd and the user's workspace."""
    return Path(__file__).resolve().parent.parent / "data" / "tilelang"
