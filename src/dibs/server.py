"""MCP server entry point exposing the `check_names` tool."""

import functools

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from dibs import checks
from dibs.models import NameReport

mcp = FastMCP("dibs")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def check_names(names: list[str], endings: list[str] | None = None) -> list[NameReport]:
    """Check candidate business names against Companies House, domains (over RDAP) and UK
    trademarks (classes 9 and 42).

    Returns one report per name, in the order given, with a verdict (clear, check manually or
    conflict) and the evidence and links behind each result. `endings` are the domain endings
    to try, with the leading dot (default .com, .co.uk, .ai, .io). Read-only: never registers,
    buys or reserves anything.
    """
    if endings is None:
        return await checks.check_names(names)
    return await checks.check_names(
        names, domain_check=functools.partial(checks.rdap_domain_check, endings=tuple(endings))
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
