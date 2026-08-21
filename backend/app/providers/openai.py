"""OpenAI adapter (Responses API, stateless).

Runs with `store=false` and `include=["reasoning.encrypted_content"]` so all
state lives in our DB. Every completed step stores the response's output items
(reasoning + message + function_call) verbatim in a single reasoning block;
on replay the adapter feeds those items back in `input`. Items are replayed
for assistant turns in the active tool loop (after the latest user message) —
matching OpenAI's "replay output items since the last user message" guidance —
and for any older turn that carries tool calls, since reasoning models reject
function_call items without their reasoning item.
"""

import json
from typing import Any

import httpx

from ..config import get_settings
from .base import ChatTurn, CompletionResult, ReasoningBlock, StreamDelta, ToolCall

API_URL = "https://api.openai.com/v1/responses"

REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class OpenAIAdapter:
    name = "openai"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _is_reasoning_model(self) -> bool:
        return self.model.startswith(REASONING_MODEL_PREFIXES)

    def _stored_items(self, turn: ChatTurn) -> list[dict] | None:
        for block in turn.reasoning:
            if block.provider == self.name and block.payload.get("items"):
                return block.payload["items"]
        return None

    def _build_input(self, history: list[ChatTurn]) -> list[dict]:
        items: list[dict[str, Any]] = []
        last_user_idx = max(
            (i for i, t in enumerate(history) if t.role == "user"), default=-1
        )
        replayed_call_ids: set[str] = set()
        for i, turn in enumerate(history):
            if turn.role == "user":
                items.append({"role": "user", "content": turn.text})
            elif turn.role == "assistant":
                stored = self._stored_items(turn)
                if stored is not None and (i > last_user_idx or turn.tool_calls):
                    items.extend(stored)
                    for item in stored:
                        if item.get("type") == "function_call" and item.get("call_id"):
                            replayed_call_ids.add(item["call_id"])
                else:
                    text = turn.text or ""
                    if turn.tool_calls:
                        calls = "; ".join(
                            f"{tc.name}({json.dumps(tc.arguments)})" for tc in turn.tool_calls
                        )
                        text = (text + f"\n[Called tools: {calls}]").strip()
                    if text:
                        items.append({"role": "assistant", "content": text})
            elif turn.role == "tool":
                if turn.tool_call_id in replayed_call_ids:
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": turn.tool_call_id,
                            "output": turn.text,
                        }
                    )
                else:
                    items.append(
                        {
                            "role": "user",
                            "content": f"[Result of tool {turn.tool_name or 'call'}]:\n{turn.text}",
                        }
                    )
        return items

    async def stream_completion(
        self,
        system_prompt: str,
        history: list[ChatTurn],
        tools: list[dict],
        on_delta,
    ) -> CompletionResult:
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": self._build_input(history),
            "stream": True,
            "store": False,
            "max_output_tokens": 16384,
        }
        if self._is_reasoning_model():
            body["include"] = ["reasoning.encrypted_content"]
            body["reasoning"] = {
                "effort": get_settings().openai_reasoning_effort,
                "summary": "auto",
            }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "parameters": t["function"]["parameters"],
                }
                for t in tools
            ]

        final_response: dict | None = None
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
                    raise RuntimeError(f"OpenAI API error {resp.status_code}: {detail[:2000]}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    ctype = chunk.get("type", "")
                    if ctype == "response.output_text.delta" and chunk.get("delta"):
                        await on_delta(StreamDelta("text", chunk["delta"]))
                    elif ctype == "response.reasoning_summary_text.delta" and chunk.get("delta"):
                        await on_delta(StreamDelta("reasoning", chunk["delta"]))
                    elif ctype == "response.completed":
                        final_response = chunk.get("response") or {}
                    elif ctype in ("response.failed", "response.incomplete"):
                        response = chunk.get("response") or {}
                        err = response.get("error") or {}
                        reason = (
                            err.get("message")
                            or (response.get("incomplete_details") or {}).get("reason")
                            or ctype
                        )
                        raise RuntimeError(f"OpenAI response did not complete: {reason}")
                    elif ctype == "error":
                        raise RuntimeError(f"OpenAI stream error: {chunk.get('message', '')}")

        if final_response is None:
            raise RuntimeError("OpenAI stream ended without a completed response")

        output_items = final_response.get("output") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        summary_parts: list[str] = []
        for item in output_items:
            itype = item.get("type")
            if itype == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
            elif itype == "function_call":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": item.get("arguments", "")}
                tool_calls.append(
                    ToolCall(id=item.get("call_id", ""), name=item.get("name", ""), arguments=args)
                )
            elif itype == "reasoning":
                for part in item.get("summary") or []:
                    if part.get("text"):
                        summary_parts.append(part["text"])

        reasoning = [
            ReasoningBlock(
                provider=self.name,
                payload={"items": output_items},
                display_text="\n\n".join(summary_parts),
            )
        ]
        return CompletionResult(
            text="".join(text_parts), reasoning=reasoning, tool_calls=tool_calls
        )
