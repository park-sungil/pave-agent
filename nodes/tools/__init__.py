from __future__ import annotations

from nodes.tools.execute_sql import execute_sql
from nodes.tools.stats_tool import stats_tool
from nodes.tools.correlation_tool import correlation_tool
from nodes.tools.interpolation_tool import interpolation_tool
from nodes.tools.ask_user import ask_user

AGENT_TOOLS = [execute_sql, stats_tool, correlation_tool, interpolation_tool, ask_user]

__all__ = [
    "execute_sql",
    "stats_tool",
    "correlation_tool",
    "interpolation_tool",
    "ask_user",
    "AGENT_TOOLS",
]
