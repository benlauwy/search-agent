"""Fireworks adapter (OpenAI Chat Completions-compatible API).

Reasoning models return `reasoning_content` on assistant messages. For
multi-turn tool calling, prior assistant turns must include their
`reasoning_content` so the model can continue its reasoning after tool
results (interleaved thinking). Models without reasoning support ignore
the extra field, so it is always included when present.
"""

import json
from typing import Any

import httpx

from .base import ChatTurn, CompletionResult, ReasoningBlock, StreamDelta, ToolCall

API_URL = "https://api.fireworks.ai/inference/v1/chat/completions"


class FireworksAdapter:
    name = "fireworks"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _build_messages(self, system_prompt: str, history: list[ChatTurn]) -> list[dict]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for turn in history:
            if turn.role == "user":
                messages.append({"role": "user", "content": turn.text})
            elif turn.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
                own_reasoning = [b for b in turn.reasoning if b.provider == self.name]
                if own_reasoning:
                    msg["reasoning_content"] = "\n".join(
                        b.payload.get("reasoning_content", "") for b in own_reasoning
                    )
                if turn.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in turn.tool_calls
                    ]
                messages.append(msg)
            elif turn.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": turn.tool_call_id,
                        "content": turn.text,
                    }
                )
        return messages

    async def stream_completion(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        tools: list[dict],
        on_delta,
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._build_messages(system_prompt, history),
            "stream": True,
            "max_tokens": 16384,
        }
        if tools:
            body["tools"] = tools

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15)) as client:
            async with client.stream(
                "POST",
                API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")
                    raise RuntimeError(f"Fireworks API error {resp.status_code}: {detail[:2000]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning_parts.append(delta["reasoning_content"])
                        await on_delta(StreamDelta("reasoning", delta["reasoning_content"]))
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        await on_delta(StreamDelta("text", delta["content"]))
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        acc = tool_calls_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            acc["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            acc["name"] += fn["name"]
                        if fn.get("arguments"):
                            acc["arguments"] += fn["arguments"]

        tool_calls = []
        for idx in sorted(tool_calls_acc):
            acc = tool_calls_acc[idx]
            try:
                args = json.loads(acc["arguments"]) if acc["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": acc["arguments"]}
            tool_calls.append(
                ToolCall(id=acc["id"] or f"call_{idx}", name=acc["name"], arguments=args)
            )

        reasoning_text = "".join(reasoning_parts)
        reasoning = (
            [
                ReasoningBlock(
                    provider=self.name,
                    payload={"reasoning_content": reasoning_text},
                    display_text=reasoning_text,
                )
            ]
            if reasoning_text
            else []
        )
        return CompletionResult(
            text="".join(text_parts), reasoning=reasoning, tool_calls=tool_calls
        )
