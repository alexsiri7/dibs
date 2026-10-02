"""Runs the Companies House, domain and trademark checks for a batch of candidate names.

Each check is pluggable. Until the real checkers land (#4, #5), the Companies House and
domain defaults never look anything up and answer "check manually" with a link to do the
check by hand. The trademark default is manual for good: the UK IPO register has no public
API and its search blocks automated clients.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import quote, quote_plus

from dibs.models import CheckResult, CheckStatus, DomainResult, DomainStatus, Evidence, NameReport

CompanyCheck = Callable[[str], Awaitable[CheckResult]]
DomainCheck = Callable[[str], Awaitable[list[DomainResult]]]
TrademarkCheck = Callable[[str], Awaitable[CheckResult]]

DEFAULT_DOMAIN_ENDINGS = (".com", ".co.uk", ".ai", ".io")
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


async def manual_domain_check(name: str) -> list[DomainResult]:
    label = re.sub(r"[\W_]", "", name.lower())
    return [
        DomainResult(
            domain=domain,
            status=DomainStatus.CHECK_MANUALLY,
            evidence=_not_checked(
                domain, "https://lookup.icann.org/en/lookup?name=" + quote(domain)
            ),
        )
        for domain in (label + ending for ending in DEFAULT_DOMAIN_ENDINGS)
    ]


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
    domain_check: DomainCheck = manual_domain_check,
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
