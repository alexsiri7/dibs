"""Runs the Companies House, domain and trademark checks for a batch of candidate names.

Each check is pluggable. Domains are looked up over RDAP. Until the real checker lands (#4),
the Companies House default never looks anything up and answers "check manually" with a link
to do the check by hand. The trademark default is manual for good: the UK IPO register has no
public API and its search blocks automated clients.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import quote, quote_plus

import httpx

from dibs.models import CheckResult, CheckStatus, DomainResult, DomainStatus, Evidence, NameReport

CompanyCheck = Callable[[str], Awaitable[CheckResult]]
DomainCheck = Callable[[str], Awaitable[list[DomainResult]]]
TrademarkCheck = Callable[[str], Awaitable[CheckResult]]

DEFAULT_DOMAIN_ENDINGS = (".com", ".co.uk", ".ai", ".io")
IANA_RDAP_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
IPO_TRADEMARK_SEARCH = "https://trademarks.ipo.gov.uk/ipo-tmtext"


def _not_checked(what: str, link: str) -> Evidence:
    return Evidence(found=f"{what} not checked automatically yet", link=link)


async def manual_company_check(name: str) -> CheckResult:
    link = (
        "https://find-and-update.company-information.service.gov.uk/search/companies?q="
        + quote_plus(name)
    )
    return CheckResult(
        status=CheckStatus.CHECK_MANUALLY, evidence=_not_checked("Companies House", link)
    )


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
    company_check: CompanyCheck = manual_company_check,
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
