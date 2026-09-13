from dataclasses import dataclass, replace


class DecisionBudgetExhausted(RuntimeError):
    """Raised when no decision allowance remains."""


@dataclass(frozen=True)
class DecisionBudget:
    max_decisions: int
    used_decisions: int = 0

    def __post_init__(self) -> None:
        for name in ("max_decisions", "used_decisions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer, not bool")
        if self.max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        if not 0 <= self.used_decisions <= self.max_decisions:
            raise ValueError("used_decisions must be between 0 and max_decisions")

    def consume(self) -> "DecisionBudget":
        if self.used_decisions >= self.max_decisions:
            raise DecisionBudgetExhausted("decision budget exhausted")
        return replace(self, used_decisions=self.used_decisions + 1)
