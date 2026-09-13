from dataclasses import dataclass, fields
from enum import StrEnum


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class VerificationState:
    syntax: VerificationStatus = VerificationStatus.NOT_RUN
    api_evidence: VerificationStatus = VerificationStatus.NOT_RUN
    compilation: VerificationStatus = VerificationStatus.NOT_RUN
    correctness: VerificationStatus = VerificationStatus.NOT_RUN
    performance: VerificationStatus = VerificationStatus.NOT_RUN

    def __post_init__(self) -> None:
        for field in fields(self):
            if not isinstance(getattr(self, field.name), VerificationStatus):
                raise TypeError(f"{field.name} must be a VerificationStatus")
