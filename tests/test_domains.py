import httpx
import respx

from dibs.checks import IANA_RDAP_BOOTSTRAP, check_names, rdap_domain_check
from dibs.models import CheckResult, CheckStatus, DomainStatus, Verdict

CLEAR = CheckResult(status=CheckStatus.CLEAR)
BOOTSTRAP = {
    "services": [
        [["com"], ["https://rdap.verisign.com/com/v1/"]],
        [["uk"], ["https://rdap.nominet.uk/uk/"]],
        [["ai"], ["https://rdap.nic.ai/"]],
        [["io"], ["https://rdap.nic.io/"]],
        [["dev"], ["https://pubapi.registry.google/rdap/"]],
    ]
}


def fixed(result):
    async def check(name: str):
        return result

    return check


def mock_bootstrap(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(IANA_RDAP_BOOTSTRAP).respond(json=BOOTSTRAP)


async def test_default_endings(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    results = await rdap_domain_check("Dibs")

    assert [d.domain for d in results] == ["dibs.com", "dibs.co.uk", "dibs.ai", "dibs.io"]
    assert all(d.status is DomainStatus.AVAILABLE for d in results)
    assert {str(c.request.url) for c in respx_mock.calls if "/domain/" in c.request.url.path} == {
        "https://rdap.verisign.com/com/v1/domain/dibs.com",
        "https://rdap.nominet.uk/uk/domain/dibs.co.uk",
        "https://rdap.nic.ai/domain/dibs.ai",
        "https://rdap.nic.io/domain/dibs.io",
    }


async def test_custom_endings(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    results = await rdap_domain_check("Dibs", endings=(".com", ".dev"))

    assert [d.domain for d in results] == ["dibs.com", "dibs.dev"]


async def test_label_drops_spaces_and_punctuation(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    results = await rdap_domain_check("Blue Fern & Co.", endings=(".com",))

    assert [d.domain for d in results] == ["bluefernco.com"]


async def test_registered_domain_is_taken_but_not_a_conflict(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get("https://rdap.verisign.com/com/v1/domain/dibs.com").respond(
        json={"objectClassName": "domain", "ldhName": "DIBS.COM"}
    )
    respx_mock.get(url__regex=r"/domain/").respond(404)

    [r] = await check_names(["Dibs"], company_check=fixed(CLEAR), trademark_check=fixed(CLEAR))

    com = r.domains[0]
    assert com.domain == "dibs.com"
    assert com.status is DomainStatus.TAKEN
    assert com.evidence.link == "https://rdap.verisign.com/com/v1/domain/dibs.com"
    assert r.verdict is Verdict.CLEAR


async def test_lookup_fails(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get("https://rdap.nic.ai/domain/dibs.ai").mock(side_effect=httpx.ConnectTimeout)
    respx_mock.get("https://rdap.nic.io/domain/dibs.io").respond(503)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    results = {d.domain: d for d in await rdap_domain_check("Dibs")}

    for domain in ("dibs.ai", "dibs.io"):
        assert results[domain].status is DomainStatus.CHECK_MANUALLY
        assert results[domain].evidence.link.endswith("lookup?name=" + domain)
    assert results["dibs.com"].status is DomainStatus.AVAILABLE


async def test_ending_without_rdap_service_needs_manual_check(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    [result] = await rdap_domain_check("Dibs", endings=(".xyz",))

    assert result.status is DomainStatus.CHECK_MANUALLY
    assert "no RDAP service" in result.evidence.found


async def test_bootstrap_unavailable_means_check_manually(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(IANA_RDAP_BOOTSTRAP).respond(500)

    results = await rdap_domain_check("Dibs")

    assert len(results) == 4
    assert all(d.status is DomainStatus.CHECK_MANUALLY for d in results)


async def test_only_reads(respx_mock: respx.MockRouter) -> None:
    mock_bootstrap(respx_mock)
    respx_mock.get(url__regex=r"/domain/").respond(404)

    await rdap_domain_check("Dibs")

    assert respx_mock.calls
    assert {c.request.method for c in respx_mock.calls} == {"GET"}
