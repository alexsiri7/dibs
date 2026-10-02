"""Runs the Companies House, domain and trademark checks for a batch of candidate names.

Each check is pluggable. Companies House is searched through its public data API, with the
API key taken from the COMPANIES_HOUSE_API_KEY environment variable. Domains are looked up over
RDAP. The trademark default is manual for good: the UK IPO register has no public API and its
search blocks automated clients.
"""

import asyncio
import os
import re
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ValidationError

from dibs.models import CheckResult, CheckStatus, DomainResult, DomainStatus, Evidence, NameReport

CompanyCheck = Callable[[str], Awaitable[CheckResult]]
DomainCheck = Callable[[str], Awaitable[list[DomainResult]]]
TrademarkCheck = Callable[[str], Awaitable[CheckResult]]

DEFAULT_DOMAIN_ENDINGS = (".com", ".co.uk", ".ai", ".io")
IANA_RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
IPO_TRADEMARK_SEARCH = "https://trademarks.ipo.gov.uk/ipo-tmtext"
COMPANIES_HOUSE_API = "https://api.company-information.service.gov.uk"
COMPANIES_HOUSE_SITE = "https://find-and-update.company-information.service.gov.uk"
COMPANIES_HOUSE_API_KEY = "COMPANIES_HOUSE_API_KEY"


class _Company(BaseModel):
    title: str
    company_number: str
    company_status: str = "unknown"


class _CompanySearch(BaseModel):
    items: list[_Company] = []


def _name_words(name: str) -> tuple[str, ...]:
    """The words Companies House compares: case, punctuation, a trailing "Limited"/"Ltd" and
    web endings are ignored."""
    name = re.sub(r"\W*\b(limited|ltd)\W*$", "", name.strip().lower())
    name = re.sub(r"\.(com|co\.uk|net|org)$", "", name.strip())
    return tuple(re.findall(r"[^\W_]+", name))


def _contains_words(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    n = len(shorter)
    return any(longer[i : i + n] == shorter for i in range(len(longer) - n + 1))


def _manual_company_check(name: str, why: str) -> CheckResult:
    return CheckResult(
        status=CheckStatus.CHECK_MANUALLY,
        evidence=Evidence(
            found=why, link=COMPANIES_HOUSE_SITE + "/search/companies?q=" + quote_plus(name)
        ),
    )


def _company_finding(status: CheckStatus, company: _Company) -> CheckResult:
    return CheckResult(
        status=status,
        evidence=Evidence(
            found=f"{company.title} ({company.company_number}), status: {company.company_status}",
            link=COMPANIES_HOUSE_SITE + "/company/" + quote(company.company_number),
        ),
    )


async def companies_house_check(name: str) -> CheckResult:
    api_key = os.environ.get(COMPANIES_HOUSE_API_KEY)
    if not api_key:
        return _manual_company_check(
            name, f"Companies House not searched: {COMPANIES_HOUSE_API_KEY} is not set"
        )
    candidate = _name_words(name)
    if not candidate:
        return _manual_company_check(name, "Nothing left to compare once endings are ignored")
    async with httpx.AsyncClient(auth=httpx.BasicAuth(api_key, "")) as client:
        try:
            response = await client.get(
                COMPANIES_HOUSE_API + "/search/companies",
                params={"q": " ".join(candidate), "items_per_page": 100},
            )
            response.raise_for_status()
            search = _CompanySearch.model_validate_json(response.content)
        except httpx.HTTPStatusError as e:
            why = f"Companies House search failed (HTTP {e.response.status_code})"
            return _manual_company_check(name, why)
        except (httpx.HTTPError, ValidationError) as e:
            return _manual_company_check(
                name, f"Companies House search failed ({type(e).__name__})"
            )

    live = [
        (company, words)
        for company in search.items
        if company.company_status != "dissolved" and (words := _name_words(company.title))
    ]
    for company, words in live:
        if "".join(words) == "".join(candidate):
            return _company_finding(CheckStatus.CONFLICT, company)
    for company, words in live:
        if _contains_words(words, candidate) or _contains_words(candidate, words):
            return _company_finding(CheckStatus.POSSIBLE_CONFLICT, company)
    return CheckResult(status=CheckStatus.CLEAR)


def _manual_domain_lookup(domain: str, why: str) -> DomainResult:
    return DomainResult(
        domain=domain,
        status=DomainStatus.CHECK_MANUALLY,
        evidence=Evidence(
            found=f"{domain}: {why}",
            link="https://lookup.icann.org/en/lookup?name=" + quote(domain),
        ),
    )


def _rdap_server(services: dict[str, str], domain: str) -> str | None:
    """Longest matching ending wins, as RFC 9224 asks."""
    labels = domain.split(".")
    for i in range(1, len(labels)):
        if server := services.get(".".join(labels[i:])):
            return server
    return None


async def _lookup_domain(client: httpx.AsyncClient, server: str, domain: str) -> DomainResult:
    url = server.rstrip("/") + "/domain/" + domain
    try:
        response = await client.get(url)
    except httpx.HTTPError as e:
        return _manual_domain_lookup(domain, f"RDAP lookup failed ({type(e).__name__})")
    if response.status_code == 404:
        return DomainResult(domain=domain, status=DomainStatus.AVAILABLE)
    if response.status_code == 200:
        return DomainResult(
            domain=domain,
            status=DomainStatus.TAKEN,
            evidence=Evidence(found=f"{domain} is registered", link=url),
        )
    return _manual_domain_lookup(domain, f"RDAP lookup failed (HTTP {response.status_code})")


async def rdap_domain_check(
    name: str, endings: Sequence[str] = DEFAULT_DOMAIN_ENDINGS
) -> list[DomainResult]:
    label = re.sub(r"[\W_]", "", name.lower())
    domains = [label + ending for ending in endings]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.get(IANA_RDAP_BOOTSTRAP)
            response.raise_for_status()
            services = {
                tld.lower(): servers[0]
                for tlds, servers in response.json()["services"]
                for tld in tlds
                if servers
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            why = f"RDAP bootstrap registry unavailable ({type(e).__name__})"
            return [_manual_domain_lookup(domain, why) for domain in domains]

        async def lookup(domain: str) -> DomainResult:
            if server := _rdap_server(services, domain):
                return await _lookup_domain(client, server, domain)
            return _manual_domain_lookup(domain, "no RDAP service for this ending")

        return list(await asyncio.gather(*(lookup(domain) for domain in domains)))


async def manual_trademark_check(name: str) -> CheckResult:
    return CheckResult(
        status=CheckStatus.CHECK_MANUALLY,
        evidence=Evidence(
            found=(
                "UK trademark register can't be searched automatically — "
                f"search the UK IPO for {name!r} in classes 9 and 42"
            ),
            link=IPO_TRADEMARK_SEARCH,
        ),
    )


async def check_names(
    names: Sequence[str],
    *,
    company_check: CompanyCheck = companies_house_check,
    domain_check: DomainCheck = rdap_domain_check,
    trademark_check: TrademarkCheck = manual_trademark_check,
) -> list[NameReport]:
    """One report per name, in the order given."""

    async def check(name: str) -> NameReport:
        companies_house, domains, trademark = await asyncio.gather(
            company_check(name), domain_check(name), trademark_check(name)
        )
        return NameReport(
            name=name, companies_house=companies_house, domains=domains, trademark=trademark
        )

    return list(await asyncio.gather(*(check(name) for name in names)))
