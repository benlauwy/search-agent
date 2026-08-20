"""Provider abstraction.

Reasoning blocks are stored verbatim as provider-native JSON, tagged with the
provider name. Each adapter serializes only its own provider's blocks back into
requests, so switching providers between runs is always safe.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ReasoningBlock:
    provider: str
    payload: dict[str, Any]
    display_text: str = ""


@dataclass
class ChatTurn:
    """Canonical message used to build provider requests."""

    role: str  # user | assistant | tool
    text: str = ""
    reasoning: list[ReasoningBlock] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class StreamDelta:
    type: str  # "text" | "reasoning"
    text: str


@dataclass
class CompletionResult:
    text: str
    reasoning: list[ReasoningBlock]
    tool_calls: list[ToolCall]


class ProviderAdapter(Protocol):
    name: str

    async def stream_completion(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        tools: list[dict],
        on_delta,
    ) -> CompletionResult:
        """Run one model call, invoking on_delta(StreamDelta) as tokens arrive."""
        ...


def turn_from_message_row(row) -> ChatTurn:
    return ChatTurn(
        role=row.role,
        text=row.text or "",
        reasoning=[ReasoningBlock(**b) for b in (row.reasoning_json or [])],
        tool_calls=[ToolCall(**t) for t in (row.tool_calls_json or [])],
        tool_call_id=row.tool_call_id,
        tool_name=row.tool_name,
    )
