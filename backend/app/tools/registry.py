from .base import Tool, tool_schema
from .files import ReadFileTool, WriteFileTool
from .subagents import SpawnSubagentsTool
from .trace import TraceSessionTool
from .web_search import WebSearchTool


def build_tools(subagent: bool = False) -> dict[str, Tool]:
    """Tool set for a run. Subagents get a restricted set: no spawn_subagents
    (depth 1) and no trace_session."""
    tools: list[Tool] = [WebSearchTool(), WriteFileTool(), ReadFileTool()]
    if not subagent:
        tools.append(TraceSessionTool())
        tools.append(SpawnSubagentsTool())
    return {t.name: t for t in tools}


def tool_schemas(tools: dict[str, Tool]) -> list[dict]:
    return [tool_schema(t) for t in tools.values()]
