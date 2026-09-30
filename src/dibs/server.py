"""MCP server entry point. Tools are registered in later issues (#3)."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dibs")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
