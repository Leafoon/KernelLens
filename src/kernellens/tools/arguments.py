from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ReadReportArguments(Arguments):
    path: str = Field(
        min_length=1,
        pattern=r"\S",
        description="待读取报告的路径；访问范围由执行器校验。",
    )


class ListFilesArguments(Arguments):
    path: str = Field(default=".", min_length=1)
    pattern: str = Field(default="*", min_length=1, max_length=200)
    limit: int = Field(default=100, ge=1, le=200)


class ReadFileArguments(ReadReportArguments):
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=200, ge=1, le=500)


class SearchArguments(ListFilesArguments):
    query: str = Field(
        min_length=1, max_length=500, description="按原文子串检索，不执行正则。"
    )


class WriteFileArguments(ReadReportArguments):
    content: str = Field(max_length=100000)
    expected_sha256: str = Field(
        default="",
        pattern=r"^(|[a-f0-9]{64})$",
        description="新文件为空；覆盖必须给出 read_file 返回的当前 SHA-256。",
    )


class RequestInputArguments(Arguments):
    question: str = Field(min_length=1, pattern=r"\S")
    reason: str = Field(min_length=1, pattern=r"\S")


class CompareReportsArguments(Arguments):
    baseline_path: str = Field(min_length=1, pattern=r"\S")
    candidate_path: str = Field(min_length=1, pattern=r"\S")


class FinishArguments(Arguments):
    answer: str = Field(min_length=1, pattern=r"\S", max_length=50000)
    reason: str = Field(min_length=1, pattern=r"\S")


class SearchKnowledgeArguments(Arguments):
    query: str = Field(min_length=1, max_length=20000, pattern=r"\S")
    index: Literal["auto", "api", "concept", "example", "compiler", "operator"] = "auto"
    top_k: int = Field(default=5, ge=1, le=10)
    max_chars: int = Field(default=10000, ge=1500, le=20000)
    target: Literal["", "cuda", "hip", "metal", "cpu", "webgpu"] = ""
    include_source: bool = Field(
        default=False,
        description="预算允许时携带短单元的完整源码；source_complete=true 才代表全文，避免重复读取。",
    )


class ReadKnowledgeArguments(Arguments):
    unit_id: str = Field(pattern=r"^K[a-f0-9]{16}$")
    start_line: int = Field(default=0, ge=0)
    max_chars: int = Field(default=10000, ge=1500, le=20000)
