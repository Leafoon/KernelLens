"""Run reproducible project checks without provider calls or GPU execution."""

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def check_docs() -> None:
    documents = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "NOTICE.md",
        *sorted((ROOT / "docs").rglob("*.md")),
    ]
    links = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        if len(re.findall(r"^```", text, re.M)) % 2:
            raise ValueError(f"Unclosed Markdown fence: {path.relative_to(ROOT)}")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (path.parent / unquote(target)).exists():
                raise ValueError(
                    f"Missing local link in {path.relative_to(ROOT)}: {target}"
                )
            links += 1
    print(
        f"PASS: {len(documents)} Markdown documents, {links} local file links; anchors and rendering not checked.",
        flush=True,
    )


def main() -> int:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "KERNELLENS_"))
        and key not in {"base_url", "api_key", "model", "BASE_URL", "API_KEY", "MODEL"}
    }
    commands = [
        ["-m", "ruff", "check", "src", "tests", "scripts"],
        ["-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        ["-m", "pytest", "-q"],
        ["-m", "kernellens.knowledge", "validate"],
        ["scripts/evaluate_knowledge.py"],
        ["scripts/sync_diagrams.py", "--check"],
    ]
    for command in commands:
        print("\n> python " + " ".join(command), flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)
    check_docs()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"Project checks failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
