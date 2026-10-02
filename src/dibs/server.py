"""MCP server entry point exposing the `check_names` tool."""

import functools

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from dibs import checks
from dibs.models import NameReport, Verdict

mcp = FastMCP(
    "dibs",
    stateless_http=True,
    json_response=True,
    # Bearer auth gates /mcp (dibs.app); the SDK's localhost-only Host check would reject the
    # public domain.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


CHECK_NAMES_DESCRIPTION = (
    "Check candidate business names against Companies House, domains (over RDAP) and UK "
    "trademarks (classes 9 and 42).\n\n"
    "Returns one report per name, in the order given, with a verdict "
    f"({', '.join(v.value for v in Verdict)}) and the evidence and links behind each result. "
    "`endings` are the domain endings to try, with the leading dot "
    f"(default {', '.join(checks.DEFAULT_DOMAIN_ENDINGS)}). "
    "When a name is taken at Companies House, its report also lists `variants`: the name with "
    f"each of `suffixes` appended (default {', '.join(checks.DEFAULT_SUFFIXES)}), each with its "
    "own verdict. "
    "Read-only: never registers, buys or reserves anything."
)


@mcp.tool(
    description=CHECK_NAMES_DESCRIPTION,
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
async def check_names(
    names: list[str], endings: list[str] | None = None, suffixes: list[str] | None = None
) -> list[NameReport]:
    domain_check = checks.rdap_domain_check
    if endings is not None:
        domain_check = functools.partial(checks.rdap_domain_check, endings=tuple(endings))
    return await checks.check_names(
        names,
        domain_check=domain_check,
        suffixes=checks.DEFAULT_SUFFIXES if suffixes is None else tuple(suffixes),
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
