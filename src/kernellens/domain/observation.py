from dataclasses import dataclass
from enum import StrEnum

from kernellens.domain.action import CallToolAction
from kernellens.domain.verification import VerificationState


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolObservation:
    action: CallToolAction
    status: ToolExecutionStatus
    content: str
    verification: VerificationState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, CallToolAction):
            raise TypeError("action must be a CallToolAction")
        if not isinstance(self.status, ToolExecutionStatus):
            raise TypeError("status must be a ToolExecutionStatus")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        if self.verification is not None and not isinstance(
            self.verification, VerificationState
        ):
            raise TypeError("verification must be a VerificationState or None")
