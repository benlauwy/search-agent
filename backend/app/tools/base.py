from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    db: AsyncSession
    session_id: str
    user_id: str
    emit: Callable[[str, dict], Awaitable[None]]


@dataclass
class ToolResult:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


class Tool(Protocol):
    name: str
    description: str
    parameters: dict  # JSON schema
    timeout_seconds: int | None  # None = use the default tool timeout

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult: ...


def tool_schema(tool: Tool) -> dict:
    """OpenAI-style function schema (also accepted by Fireworks)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
