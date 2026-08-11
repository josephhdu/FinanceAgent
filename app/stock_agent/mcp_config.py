"""Factory for the finance MCP toolset.

Each agent requests only the tools it needs via ``tool_filter`` — least-privilege
tool access (arch/Architecture.md 5.11). The MCP server runs as a stdio
subprocess launched with the same Python interpreter as the web server.
"""
from __future__ import annotations

import os
import sys

from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)

# Directory containing the ``stock_agent`` package (the app root). Used as the
# subprocess cwd so ``python -m stock_agent.finance_mcp_server`` resolves.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_finance_toolset(tool_filter: list[str]) -> McpToolset:
    """Build an McpToolset exposing only the named finance tools."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "stock_agent.finance_mcp_server"],
        cwd=_APP_DIR,
        env={**os.environ},
    )
    return McpToolset(
        connection_params=StdioConnectionParams(server_params=server_params, timeout=30.0),
        tool_filter=tool_filter,
    )
