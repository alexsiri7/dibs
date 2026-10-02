import respx

from dibs.checks import IPO_TRADEMARK_SEARCH, check_names, manual_trademark_check
from dibs.models import CheckResult, CheckStatus, DomainResult, DomainStatus, Verdict

CLEAR = CheckResult(status=CheckStatus.CLEAR)


def fixed(result):
    async def check(name: str):
        return result

    return check


async def test_register_unavailable_means_check_manually() -> None:
    result = await manual_trademark_check("Dibs")

    assert result.status is CheckStatus.CHECK_MANUALLY
    assert result.evidence.link == IPO_TRADEMARK_SEARCH
    assert result.evidence.link.startswith("https://trademarks.ipo.gov.uk/")
    for detail in ("Dibs", "9", "42"):
        assert detail in result.evidence.found


@respx.mock(assert_all_mocked=True)
async def test_trademark_never_reported_clear() -> None:
    [r] = await check_names(
        ["Dibs"],
        company_check=fixed(CLEAR),
        domain_check=fixed([DomainResult(domain="dibs.com", status=DomainStatus.AVAILABLE)]),
    )

    assert r.trademark.status is CheckStatus.CHECK_MANUALLY
    assert r.verdict is Verdict.CHECK_MANUALLY
    assert not respx.calls
