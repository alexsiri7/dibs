import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session

from dibs import server
from dibs.checks import COMPANIES_HOUSE_API, COMPANIES_HOUSE_API_KEY, IANA_RDAP_BOOTSTRAP

BOOTSTRAP = {
    "services": [
        [["com"], ["https://rdap.verisign.com/com/v1/"]],
        [["uk"], ["https://rdap.nominet.uk/uk/"]],
        [["ai"], ["https://rdap.nic.ai/"]],
        [["io"], ["https://rdap.nic.io/"]],
        [["dev"], ["https://pubapi.registry.google/rdap/"]],
    ]
}


def mock_rdap(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(IANA_RDAP_BOOTSTRAP).respond(json=BOOTSTRAP)
    respx_mock.get(url__regex=r"/domain/").respond(404)


async def call_check_names(arguments: dict) -> list[dict]:
    async with create_connected_server_and_client_session(server.mcp) as session:
        result = await session.call_tool("check_names", arguments)
    assert not result.isError
    return result.structuredContent["result"]


async def test_exposes_one_read_only_tool() -> None:
    async with create_connected_server_and_client_session(server.mcp) as session:
        tools = (await session.list_tools()).tools

    assert [t.name for t in tools] == ["check_names"]
    assert tools[0].annotations.readOnlyHint is True


async def test_check_from_claude(respx_mock: respx.MockRouter) -> None:
    mock_rdap(respx_mock)

    reports = await call_check_names({"names": ["Messier", "Onoma"]})

    assert [r["name"] for r in reports] == ["Messier", "Onoma"]
    for report in reports:
        assert report["verdict"] in {"clear", "check manually", "conflict"}
        for check in (report["companies_house"], report["trademark"]):
            assert {"found", "link"} <= check["evidence"].keys()
    assert [d["domain"] for d in reports[0]["domains"]] == [
        "messier.com",
        "messier.co.uk",
        "messier.ai",
        "messier.io",
    ]
    assert len(reports[1]["domains"]) == 4


async def test_custom_endings_from_the_client(respx_mock: respx.MockRouter) -> None:
    mock_rdap(respx_mock)

    [report] = await call_check_names({"names": ["Dibs"], "endings": [".com", ".dev"]})

    assert [d["domain"] for d in report["domains"]] == ["dibs.com", "dibs.dev"]


async def test_empty_endings_means_no_domain_checks(respx_mock: respx.MockRouter) -> None:
    mock_rdap(respx_mock)

    [report] = await call_check_names({"names": ["Dibs"], "endings": []})

    assert report["domains"] == []


async def test_custom_suffixes_from_the_client(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COMPANIES_HOUSE_API_KEY, "test-key")
    mock_rdap(respx_mock)
    taken = {"items": [{"title": "DIBS LTD", "company_number": "12345678"}]}
    respx_mock.get(COMPANIES_HOUSE_API + "/search/companies", params={"q": "dibs"}).respond(
        json=taken
    )
    respx_mock.get(COMPANIES_HOUSE_API + "/search/companies").respond(json={"items": []})

    [report] = await call_check_names({"names": ["Dibs"], "endings": [], "suffixes": ["Ventures"]})

    assert report["verdict"] == "conflict"
    assert [v["name"] for v in report["variants"]] == ["Dibs Ventures"]
    assert report["variants"][0]["companies_house"]["status"] == "clear"
    assert report["variants"][0]["variants"] == []
