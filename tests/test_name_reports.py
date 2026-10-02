import pytest
import respx
from pydantic import ValidationError

from dibs.checks import IANA_RDAP_BOOTSTRAP, check_names
from dibs.models import (
    CheckResult,
    CheckStatus,
    DomainResult,
    DomainStatus,
    Evidence,
    NameReport,
    Verdict,
)

CLEAR = CheckResult(status=CheckStatus.CLEAR)
COMPANY_CONFLICT = CheckResult(
    status=CheckStatus.CONFLICT,
    evidence=Evidence(
        found="Active company INTERSTELLAR AI LTD (12345678)",
        link="https://find-and-update.company-information.service.gov.uk/company/12345678",
    ),
)
NEEDS_LOOK = Evidence(found="Register unavailable", link="https://trademarks.ipo.gov.uk/")


def report(
    companies_house: CheckResult = CLEAR,
    domains: list[DomainResult] | None = None,
    trademark: CheckResult = CLEAR,
) -> NameReport:
    if domains is None:
        domains = [DomainResult(domain="dibs.com", status=DomainStatus.AVAILABLE)]
    return NameReport(
        name="Dibs", companies_house=companies_house, domains=domains, trademark=trademark
    )


def fixed(result):
    async def check(name: str):
        return result

    return check


async def test_three_candidates_reported_in_order(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(IANA_RDAP_BOOTSTRAP).respond(500)
    reports = await check_names(["Messier", "Onoma", "Dibs"])

    assert [r.name for r in reports] == ["Messier", "Onoma", "Dibs"]
    for r in reports:
        assert r.companies_house
        assert r.domains
        assert r.trademark


async def test_unchecked_names_need_a_manual_check_with_links(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(IANA_RDAP_BOOTSTRAP).respond(500)
    [r] = await check_names(["Blue Fern"])

    assert r.verdict is Verdict.CHECK_MANUALLY
    assert [d.domain for d in r.domains] == [
        "bluefern.com",
        "bluefern.co.uk",
        "bluefern.ai",
        "bluefern.io",
    ]
    for result in (r.companies_house, r.trademark, *r.domains):
        assert result.evidence.link.startswith("https://")


def test_one_conflict_wins() -> None:
    assert report(companies_house=COMPANY_CONFLICT).verdict is Verdict.CONFLICT


def test_trademark_conflict_wins() -> None:
    trademark = CheckResult(
        status=CheckStatus.CONFLICT,
        evidence=Evidence(
            found="Registered UK trademark DIBS in class 9",
            link="https://trademarks.ipo.gov.uk/ipo-tmcase/page/Results/1/UK00001234567",
        ),
    )
    assert report(trademark=trademark).verdict is Verdict.CONFLICT


def test_conflict_beats_manual_check() -> None:
    r = report(
        companies_house=COMPANY_CONFLICT,
        trademark=CheckResult(status=CheckStatus.CHECK_MANUALLY, evidence=NEEDS_LOOK),
    )
    assert r.verdict is Verdict.CONFLICT


@pytest.mark.parametrize("status", [CheckStatus.CHECK_MANUALLY, CheckStatus.POSSIBLE_CONFLICT])
def test_manual_check_needed(status: CheckStatus) -> None:
    r = report(trademark=CheckResult(status=status, evidence=NEEDS_LOOK))
    assert r.verdict is Verdict.CHECK_MANUALLY


def test_failed_domain_lookup_needs_manual_check() -> None:
    domain = DomainResult(domain="dibs.ai", status=DomainStatus.CHECK_MANUALLY, evidence=NEEDS_LOOK)
    assert report(domains=[domain]).verdict is Verdict.CHECK_MANUALLY


def test_all_clear() -> None:
    assert report().verdict is Verdict.CLEAR


def test_taken_domain_alone_is_not_a_conflict() -> None:
    taken = DomainResult(
        domain="dibs.com",
        status=DomainStatus.TAKEN,
        evidence=Evidence(found="dibs.com is registered", link="https://rdap.org/domain/dibs.com"),
    )
    assert report(domains=[taken]).verdict is Verdict.CLEAR


async def test_company_conflict_evidence() -> None:
    [r] = await check_names(
        ["Interstellar AI"],
        company_check=fixed(COMPANY_CONFLICT),
        domain_check=fixed([]),
        trademark_check=fixed(CLEAR),
    )

    assert r.verdict is Verdict.CONFLICT
    assert "INTERSTELLAR AI LTD" in r.companies_house.evidence.found
    assert "12345678" in r.companies_house.evidence.found
    assert r.companies_house.evidence.link.endswith("/company/12345678")


@pytest.mark.parametrize(
    "result",
    [
        lambda: CheckResult(status=CheckStatus.CONFLICT),
        lambda: CheckResult(status=CheckStatus.POSSIBLE_CONFLICT),
        lambda: CheckResult(status=CheckStatus.CHECK_MANUALLY),
        lambda: DomainResult(domain="dibs.com", status=DomainStatus.TAKEN),
        lambda: DomainResult(domain="dibs.com", status=DomainStatus.CHECK_MANUALLY),
    ],
)
def test_findings_must_carry_evidence(result) -> None:
    with pytest.raises(ValidationError):
        result()


def test_verdict_is_serialised_with_the_report() -> None:
    assert report().model_dump()["verdict"] == "clear"


@respx.mock(assert_all_mocked=True)
async def test_clear_name_registers_nothing() -> None:
    [r] = await check_names(
        ["Dibs"],
        company_check=fixed(CLEAR),
        domain_check=fixed([DomainResult(domain="dibs.com", status=DomainStatus.AVAILABLE)]),
        trademark_check=fixed(CLEAR),
    )

    assert r.verdict is Verdict.CLEAR
    assert not respx.calls


async def test_base_name_taken_reports_variants() -> None:
    async def company_check(name: str) -> CheckResult:
        return COMPANY_CONFLICT if name == "Interstellar AI" else CLEAR

    [r] = await check_names(
        ["Interstellar AI"],
        company_check=company_check,
        domain_check=fixed([]),
        trademark_check=fixed(CLEAR),
    )

    assert r.verdict is Verdict.CONFLICT
    assert [(v.name, v.verdict) for v in r.variants] == [
        ("Interstellar AI Labs", Verdict.CLEAR),
        ("Interstellar AI Studio", Verdict.CLEAR),
    ]


async def test_variants_are_not_suffixed_again() -> None:
    [r] = await check_names(
        ["Interstellar AI"],
        company_check=fixed(COMPANY_CONFLICT),
        domain_check=fixed([]),
        trademark_check=fixed(CLEAR),
    )

    assert [v.verdict for v in r.variants] == [Verdict.CONFLICT, Verdict.CONFLICT]
    assert all(v.variants == [] for v in r.variants)


@pytest.mark.parametrize(
    "companies_house",
    [CLEAR, CheckResult(status=CheckStatus.POSSIBLE_CONFLICT, evidence=NEEDS_LOOK)],
)
async def test_base_name_free_reports_no_variants(companies_house: CheckResult) -> None:
    [r] = await check_names(
        ["Dibs"],
        company_check=fixed(companies_house),
        domain_check=fixed([]),
        trademark_check=fixed(CLEAR),
    )

    assert r.variants == []


async def test_trademark_only_conflict_reports_no_variants() -> None:
    trademark_conflict = CheckResult(
        status=CheckStatus.CONFLICT,
        evidence=Evidence(
            found="Registered UK trademark DIBS", link="https://trademarks.ipo.gov.uk/"
        ),
    )

    [r] = await check_names(
        ["Dibs"],
        company_check=fixed(CLEAR),
        domain_check=fixed([]),
        trademark_check=fixed(trademark_conflict),
    )

    assert r.verdict is Verdict.CONFLICT
    assert r.variants == []
