"""Anthropic adapter (Messages API with extended thinking).

`thinking`/`redacted_thinking` blocks carry cryptographic signatures and must
be echoed back complete and unmodified on the assistant message when returning
tool results — the API rejects the request otherwise. Each block is stored
verbatim as a reasoning block and replayed (prepended to the assistant
content) for turns in the active tool loop; older turns replay without
thinking, which the API tolerates.
"""

import json
from typing import Any

import httpx

from ..config import get_settings
from .base import ChatTurn, CompletionResult, ReasoningBlock, StreamDelta, ToolCall

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _build_messages(self, history: list[ChatTurn]) -> list[dict]:
        messages: list[dict[str, Any]] = []
        last_user_idx = max(
            (i for i, t in enumerate(history) if t.role == "user"), default=-1
        )

        def append_user_blocks(blocks: list[dict]) -> None:
            # Consecutive tool results must land in a single user message.
            if messages and messages[-1]["role"] == "user" and isinstance(
                messages[-1]["content"], list
            ):
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": "user", "content": blocks})

        for i, turn in enumerate(history):
            if turn.role == "user":
                # Merge into a preceding tool-result user message (cancelled or
                # max-step runs can leave tool results as the last turns); the
                # API requires alternating roles.
                append_user_blocks([{"type": "text", "text": turn.text}])
            elif turn.role == "assistant":
                content: list[dict[str, Any]] = []
                if i > last_user_idx:
                    content.extend(
                        b.payload for b in turn.reasoning if b.provider == self.name and b.payload
                    )
                if turn.text:
                    content.append({"type": "text", "text": turn.text})
                for tc in turn.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                if content:
                    messages.append({"role": "assistant", "content": content})
            elif turn.role == "tool":
                append_user_blocks(
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": turn.tool_call_id,
                            "content": turn.text,
                        }
                    ]
                )
        return messages

    async def stream_completion(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        tools: list[dict],
        on_delta,
    ) -> CompletionResult:
        settings = get_settings()
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16384,
            "system": system_prompt,
            "messages": self._build_messages(history),
            "stream": True,
            "thinking": {
                "type": "enabled",
                "budget_tokens": settings.anthropic_thinking_budget,
            },
        }
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]

        # Accumulate content blocks by index as they stream.
        blocks: dict[int, dict[str, Any]] = {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15)) as client:
            async with client.stream(
                "POST",
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": API_VERSION,
                    "Content-Type": "application/json",
                },
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")
                    raise RuntimeError(f"Anthropic API error {resp.status_code}: {detail[:2000]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    chunk = json.loads(data)
                    ctype = chunk.get("type", "")
                    if ctype == "content_block_start":
                        idx = chunk["index"]
                        block = dict(chunk.get("content_block") or {})
                        if block.get("type") == "tool_use":
                            block["_partial_json"] = ""
                        blocks[idx] = block
                    elif ctype == "content_block_delta":
                        idx = chunk["index"]
                        block = blocks.setdefault(idx, {"type": "text", "text": ""})
                        delta = chunk.get("delta") or {}
                        dtype = delta.get("type", "")
                        if dtype == "text_delta":
                            block["text"] = block.get("text", "") + delta.get("text", "")
                            await on_delta(StreamDelta("text", delta.get("text", "")))
                        elif dtype == "thinking_delta":
                            block["thinking"] = block.get("thinking", "") + delta.get(
                                "thinking", ""
                            )
                            await on_delta(StreamDelta("reasoning", delta.get("thinking", "")))
                        elif dtype == "signature_delta":
                            block["signature"] = block.get("signature", "") + delta.get(
                                "signature", ""
                            )
                        elif dtype == "input_json_delta":
                            block["_partial_json"] = block.get("_partial_json", "") + delta.get(
                                "partial_json", ""
                            )
                    elif ctype == "error":
                        err = chunk.get("error") or {}
                        raise RuntimeError(f"Anthropic stream error: {err.get('message', '')}")

        text_parts: list[str] = []
        reasoning: list[ReasoningBlock] = []
        tool_calls: list[ToolCall] = []
        for idx in sorted(blocks):
            block = blocks[idx]
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "thinking":
                payload = {
                    "type": "thinking",
                    "thinking": block.get("thinking", ""),
                    "signature": block.get("signature", ""),
                }
                reasoning.append(
                    ReasoningBlock(
                        provider=self.name,
                        payload=payload,
                        display_text=block.get("thinking", ""),
                    )
                )
            elif btype == "redacted_thinking":
                reasoning.append(
                    ReasoningBlock(
                        provider=self.name,
                        payload={"type": "redacted_thinking", "data": block.get("data", "")},
                        display_text="",
                    )
                )
            elif btype == "tool_use":
                raw = block.get("_partial_json", "")
                if raw:
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {"_raw": raw}
                else:
                    args = block.get("input") or {}
                tool_calls.append(
                    ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=args)
                )

        return CompletionResult(
            text="".join(text_parts), reasoning=reasoning, tool_calls=tool_calls
        )
