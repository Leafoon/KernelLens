"""Shared redaction and safe terminal rendering."""

import re


class Redactor:
    def __init__(self, *secrets: str):
        self.secrets = tuple(secret for secret in secrets if secret)

    def __call__(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
        return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", text)


def terminal_text(text: str) -> str:
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(
        char
        for char in text
        if char in "\n\t" or (ord(char) >= 32 and ord(char) != 127)
    )
