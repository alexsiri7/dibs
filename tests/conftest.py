import pytest

from dibs.checks import COMPANIES_HOUSE_API_KEY


@pytest.fixture(autouse=True)
def no_companies_house_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key in the developer's environment must not send tests to the live register."""
    monkeypatch.delenv(COMPANIES_HOUSE_API_KEY, raising=False)
