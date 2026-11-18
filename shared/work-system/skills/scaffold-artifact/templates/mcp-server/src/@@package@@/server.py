"""The MCP server: its tools, over a Backend, so tests can run every tool on a fake."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .backend import Backend, Item

NAME = "@@project@@"


def build_server(backend: Backend) -> MCPServer:
    server = MCPServer(NAME, instructions="@@description@@")

    @server.tool()
    def search(query: str, limit: int = 5) -> list[Item]:
        """Find items whose title matches the query; at most `limit` (1 to 50) of them."""
        if not query.strip():
            raise ValueError("query must not be empty")
        return backend.search(query, max(1, min(limit, 50)))

    return server
