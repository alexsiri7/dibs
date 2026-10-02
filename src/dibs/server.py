"""MCP server entry point exposing the `check_names` tool."""

import functools

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from dibs import checks
from dibs.models import NameReport, Verdict

mcp = FastMCP("dibs")


CHECK_NAMES_DESCRIPTION = (
    "Check candidate business names against Companies House, domains (over RDAP) and UK "
    "trademarks (classes 9 and 42).\n\n"
    "Returns one report per name, in the order given, with a verdict "
    f"({', '.join(v.value for v in Verdict)}) and the evidence and links behind each result. "
    "`endings` are the domain endings to try, with the leading dot "
    f"(default {', '.join(checks.DEFAULT_DOMAIN_ENDINGS)}). "
    "Read-only: never registers, buys or reserves anything."
)


@mcp.tool(
    description=CHECK_NAMES_DESCRIPTION,
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
async def check_names(names: list[str], endings: list[str] | None = None) -> list[NameReport]:
    if endings is None:
        return await checks.check_names(names)
    return await checks.check_names(
        names, domain_check=functools.partial(checks.rdap_domain_check, endings=tuple(endings))
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
