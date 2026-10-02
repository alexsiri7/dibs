from base64 import b64encode

import httpx
import pytest
import respx

from dibs.checks import COMPANIES_HOUSE_API, COMPANIES_HOUSE_API_KEY, companies_house_check
from dibs.models import CheckStatus

SEARCH = COMPANIES_HOUSE_API + "/search/companies"
SITE = "https://find-and-update.company-information.service.gov.uk"


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(COMPANIES_HOUSE_API_KEY, "test-key")


def company(title: str, number: str = "12345678", status: str = "active") -> dict:
    return {"title": title, "company_number": number, "company_status": status}


def mock_search(respx_mock: respx.MockRouter, *companies: dict) -> respx.Route:
    return respx_mock.get(SEARCH).respond(json={"items": list(companies)})


@pytest.mark.usefixtures("api_key")
async def test_web_ending_ignored(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("INTERSTELLAR AI LTD"))

    result = await companies_house_check("interstellarai.net")

    assert result.status is CheckStatus.CONFLICT
    assert "INTERSTELLAR AI LTD" in result.evidence.found
    assert "12345678" in result.evidence.found
    assert result.evidence.link == SITE + "/company/12345678"


@pytest.mark.usefixtures("api_key")
async def test_case_and_spacing_ignored(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("BLUE FERN LIMITED", "87654321"))

    result = await companies_house_check("BLUEFERN")

    assert result.status is CheckStatus.CONFLICT
    assert result.evidence.link == SITE + "/company/87654321"


@pytest.mark.usefixtures("api_key")
async def test_punctuation_and_company_type_ignored(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("BLUE-FERN LTD."))

    result = await companies_house_check("Blue Fern Limited")

    assert result.status is CheckStatus.CONFLICT


@pytest.mark.usefixtures("api_key")
async def test_dissolved_company(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("BLUE FERN LIMITED", status="dissolved"))

    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.CLEAR


@pytest.mark.usefixtures("api_key")
async def test_name_with_an_extra_word(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("INTERSTELLAR AI LTD"))

    result = await companies_house_check("Interstellar AI Labs")

    assert result.status is CheckStatus.POSSIBLE_CONFLICT
    assert "INTERSTELLAR AI LTD" in result.evidence.found


@pytest.mark.usefixtures("api_key")
async def test_company_with_an_extra_word(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("BLUE FERN STUDIO LTD"))

    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.POSSIBLE_CONFLICT


@pytest.mark.usefixtures("api_key")
async def test_part_of_a_word_is_not_a_near_match(respx_mock: respx.MockRouter) -> None:
    mock_search(respx_mock, company("FERNWOOD LTD"))

    result = await companies_house_check("Fern")

    assert result.status is CheckStatus.CLEAR


@pytest.mark.usefixtures("api_key")
async def test_same_name_beats_near_match(respx_mock: respx.MockRouter) -> None:
    mock_search(
        respx_mock,
        company("BLUE FERN STUDIO LTD", "11111111"),
        company("BLUE FERN LTD", "22222222"),
    )

    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.CONFLICT
    assert result.evidence.link.endswith("/company/22222222")


@pytest.mark.usefixtures("api_key")
async def test_no_results(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(SEARCH).respond(json={"total_results": 0})

    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.CLEAR


@pytest.mark.usefixtures("api_key")
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, json={"items": [{"title": "BLUE FERN LTD"}]}),
        httpx.Response(200, text="not json"),
        httpx.ConnectTimeout("timed out"),
    ],
)
async def test_search_fails(respx_mock: respx.MockRouter, response) -> None:
    route = respx_mock.get(SEARCH)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)

    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.CHECK_MANUALLY
    assert result.evidence.link == SITE + "/search/companies?q=Blue+Fern"


@respx.mock(assert_all_mocked=True)
async def test_without_api_key_means_check_manually() -> None:
    result = await companies_house_check("Blue Fern")

    assert result.status is CheckStatus.CHECK_MANUALLY
    assert COMPANIES_HOUSE_API_KEY in result.evidence.found
    assert not respx.calls


@pytest.mark.usefixtures("api_key")
async def test_nothing_left_after_normalisation(respx_mock: respx.MockRouter) -> None:
    route = mock_search(respx_mock, company("BLUE FERN LTD"))

    result = await companies_house_check("Ltd")

    assert result.status is CheckStatus.CHECK_MANUALLY
    assert not route.calls


@pytest.mark.usefixtures("api_key")
async def test_only_reads_with_key_as_username(respx_mock: respx.MockRouter) -> None:
    route = mock_search(respx_mock)

    await companies_house_check("Blue Fern Ltd")

    [call] = route.calls
    assert call.request.method == "GET"
    assert call.request.url.params["q"] == "blue fern"
    assert call.request.headers["authorization"] == "Basic " + b64encode(b"test-key:").decode()
