"""Name reports: per-check results with evidence, and the verdict they add up to."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, computed_field, model_validator


class Verdict(StrEnum):
    CLEAR = "clear"
    CHECK_MANUALLY = "check manually"
    CONFLICT = "conflict"


class CheckStatus(StrEnum):
    """Outcome of the Companies House or trademark check."""

    CLEAR = "clear"
    POSSIBLE_CONFLICT = "possible conflict"
    CONFLICT = "conflict"
    CHECK_MANUALLY = "check manually"


class DomainStatus(StrEnum):
    """Outcome of one domain lookup. Deliberately has no "conflict": a taken domain
    never makes a verdict a conflict on its own."""

    AVAILABLE = "available"
    TAKEN = "taken"
    CHECK_MANUALLY = "check manually"


class Evidence(BaseModel):
    found: str
    link: str


def _require_evidence(status: StrEnum, nothing_found: StrEnum, evidence: Evidence | None) -> None:
    if status is not nothing_found and evidence is None:
        raise ValueError(f"a {status.value!r} result must say what was found and link to it")


class CheckResult(BaseModel):
    status: CheckStatus
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def _evidence_backs_findings(self) -> Self:
        _require_evidence(self.status, CheckStatus.CLEAR, self.evidence)
        return self


class DomainResult(BaseModel):
    domain: str
    status: DomainStatus
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def _evidence_backs_findings(self) -> Self:
        _require_evidence(self.status, DomainStatus.AVAILABLE, self.evidence)
        return self


class NameReport(BaseModel):
    name: str
    companies_house: CheckResult
    domains: list[DomainResult]
    trademark: CheckResult
    variants: list["NameReport"] = []

    @computed_field
    @property
    def verdict(self) -> Verdict:
        checks = (self.companies_house.status, self.trademark.status)
        if CheckStatus.CONFLICT in checks:
            return Verdict.CONFLICT
        if (
            CheckStatus.POSSIBLE_CONFLICT in checks
            or CheckStatus.CHECK_MANUALLY in checks
            or any(d.status is DomainStatus.CHECK_MANUALLY for d in self.domains)
        ):
            return Verdict.CHECK_MANUALLY
        return Verdict.CLEAR
