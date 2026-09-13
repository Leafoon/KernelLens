from dataclasses import FrozenInstanceError

import pytest

from kernellens.domain.state import TaskStatus
from kernellens.domain.verification import VerificationState, VerificationStatus


@pytest.mark.parametrize(
    "check_name",
    ["syntax", "api_evidence", "compilation", "correctness", "performance"],
)
def test_new_checks_start_as_not_run(check_name):
    checks = VerificationState()

    assert getattr(checks, check_name) is VerificationStatus.NOT_RUN


def test_checks_can_have_different_outcomes():
    checks = VerificationState(
        syntax=VerificationStatus.PASSED,
        api_evidence=VerificationStatus.INCONCLUSIVE,
        compilation=VerificationStatus.FAILED,
    )

    assert checks.syntax is VerificationStatus.PASSED
    assert checks.api_evidence is VerificationStatus.INCONCLUSIVE
    assert checks.compilation is VerificationStatus.FAILED
    assert checks.correctness is VerificationStatus.NOT_RUN
    assert checks.performance is VerificationStatus.NOT_RUN


@pytest.mark.parametrize("value", ["passed", TaskStatus.FAILED, None, True])
def test_rejects_values_from_wrong_type(value):
    with pytest.raises(TypeError, match="compilation"):
        VerificationState(compilation=value)


def test_snapshot_cannot_be_rewritten():
    checks = VerificationState()

    with pytest.raises(FrozenInstanceError):
        checks.syntax = VerificationStatus.PASSED
