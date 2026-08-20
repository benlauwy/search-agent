from .base import Tool, tool_schema
from .files import ReadFileTool, WriteFileTool
from .web_search import WebSearchTool


def build_tools(subagent: bool = False) -> dict[str, Tool]:
    """Tool set for a run. Subagents get the same tools minus spawn_subagents
    (added in milestone 4); they can never spawn further subagents."""
    tools: dict[str, Tool] = {}
    for tool in (WebSearchTool(), WriteFileTool(), ReadFileTool()):
        tools[tool.name] = tool
    return tools


def tool_schemas(tools: dict[str, Tool]) -> list[dict]:
    return [tool_schema(t) for t in tools.values()]
