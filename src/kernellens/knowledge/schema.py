"""Stable, JSON-serializable semantic units and provenance."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

INDEXES = ("api", "concept", "example", "compiler", "operator")
SCHEMA_VERSION = 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SourceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class KnowledgeUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    category: Literal[
        "api", "instruction", "concept", "operator", "compiler", "example"
    ]
    name: str
    description: str
    when_to_use: str
    parameters: list[dict] = Field(default_factory=list)
    returns: str = ""
    examples: list[dict] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    source_location: SourceLocation
    keywords: list[str] = Field(default_factory=list)
    indexes: list[Literal["api", "concept", "example", "compiler", "operator"]]
    layer: Literal["user", "implementation"]
    visibility: Literal["public", "module", "internal", "example", "documentation"]
    aliases: list[str] = Field(default_factory=list)
    signature: str = ""
    symbols: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    evidence_quality: Literal["source", "documentation", "example", "structural"]
    source_revision: str
    source_hash: str
    content: str
    context: str = ""
    cautions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    hardware_mapping: list[str] = Field(default_factory=list)
    operator_structure: dict = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)


def unit_id(category: str, path: str, name: str) -> str:
    # Lines are deliberately excluded: unrelated lines moving do not change identity.
    return "K" + sha256(f"{category}:{path}:{name}".encode())[:16]
