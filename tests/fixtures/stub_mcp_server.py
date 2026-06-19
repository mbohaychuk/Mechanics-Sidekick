"""A minimal FastMCP server used by host integration tests. No hardware, no network."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("stub")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo(text: str) -> str:
    return f"echo:{text}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def wipe() -> str:
    return "wiped"


if __name__ == "__main__":
    mcp.run()
