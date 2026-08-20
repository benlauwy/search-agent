"""The agentic loop: model -> tool calls -> results -> model, until a final answer."""

import asyncio
import dataclasses
import uuid

from sqlalchemy import func, select

from ..config import get_settings
from ..db import SessionLocal
from ..models import ChatSession, Event, Message
from ..providers.base import ChatTurn, StreamDelta, turn_from_message_row
from ..providers.registry import build_adapter
from ..tools.base import ToolContext, ToolResult
from ..tools.registry import build_tools, tool_schemas
from .bus import bus

SYSTEM_PROMPT = """\
You are a research assistant with tools. Work in steps: search the web when you \
need current or factual information, read files the user uploaded when relevant, \
and write Markdown files when the user asks for a document or report they can \
download. Cite source URLs when you use web results. Think carefully before \
acting, and give concise, well-structured final answers.\
"""

_active_runs: dict[str, asyncio.Task] = {}


def is_running(session_id: str) -> bool:
    task = _active_runs.get(session_id)
    return task is not None and not task.done()


def cancel_run(session_id: str) -> bool:
    task = _active_runs.get(session_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def start_run(session_id: str, user_id: str) -> str:
    run_id = uuid.uuid4().hex
    task = asyncio.create_task(_run(session_id, user_id, run_id))
    _active_runs[session_id] = task

    def _cleanup(done: asyncio.Task) -> None:
        if _active_runs.get(session_id) is done:
            del _active_runs[session_id]

    task.add_done_callback(_cleanup)
    return run_id


async def _next_idx(db, model, session_id: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(model.idx), -1)).where(model.session_id == session_id)
    )
    return result.scalar_one() + 1


async def _run(session_id: str, user_id: str, run_id: str) -> None:
    settings = get_settings()
    event_idx = 0

    async def emit(event_type: str, payload: dict) -> None:
        nonlocal event_idx
        idx = event_idx
        event_idx += 1
        event = {"type": event_type, "run_id": run_id, "payload": payload}
        await bus.publish(session_id, event)
        async with SessionLocal() as edb:
            edb.add(
                Event(
                    session_id=session_id,
                    run_id=run_id,
                    idx=idx,
                    type=event_type,
                    payload_json=payload,
                )
            )
            await edb.commit()

    try:
        async with SessionLocal() as db:
            session = await db.get(ChatSession, session_id)
            adapter = await build_adapter(db, session.provider, session.model)
            tools = build_tools()
            schemas = tool_schemas(tools)

            rows = (
                await db.execute(
                    select(Message).where(Message.session_id == session_id).order_by(Message.idx)
                )
            ).scalars().all()
            history = [turn_from_message_row(r) for r in rows]

        await emit("run_started", {"provider": adapter.name, "model": adapter.model})

        for _step in range(settings.max_steps_per_run):
            async def on_delta(delta: StreamDelta) -> None:
                await bus.publish(
                    session_id,
                    {
                        "type": f"{delta.type}_delta",
                        "run_id": run_id,
                        "payload": {"text": delta.text},
                    },
                )

            result = await adapter.stream_completion(SYSTEM_PROMPT, history, schemas, on_delta)

            assistant_turn = ChatTurn(
                role="assistant",
                text=result.text,
                reasoning=result.reasoning,
                tool_calls=result.tool_calls,
            )
            history.append(assistant_turn)
            async with SessionLocal() as db:
                db.add(
                    Message(
                        session_id=session_id,
                        idx=await _next_idx(db, Message, session_id),
                        role="assistant",
                        text=result.text,
                        reasoning_json=[dataclasses.asdict(b) for b in result.reasoning],
                        tool_calls_json=[dataclasses.asdict(t) for t in result.tool_calls]
                        or None,
                    )
                )
                await db.commit()
            await emit(
                "assistant_message",
                {
                    "text": result.text,
                    "reasoning": [b.display_text for b in result.reasoning if b.display_text],
                    "tool_calls": [dataclasses.asdict(t) for t in result.tool_calls],
                },
            )

            if not result.tool_calls:
                break

            tool_results = await asyncio.gather(
                *[
                    _execute_tool(tools, tc, session_id, user_id, emit)
                    for tc in result.tool_calls
                ]
            )
            for tc, tr in zip(result.tool_calls, tool_results, strict=True):
                content = tr.content
                if len(content) > settings.tool_result_max_chars:
                    content = (
                        content[: settings.tool_result_max_chars]
                        + f"\n[truncated {len(content) - settings.tool_result_max_chars} chars]"
                    )
                tool_turn = ChatTurn(
                    role="tool", text=content, tool_call_id=tc.id, tool_name=tc.name
                )
                history.append(tool_turn)
                async with SessionLocal() as db:
                    db.add(
                        Message(
                            session_id=session_id,
                            idx=await _next_idx(db, Message, session_id),
                            role="tool",
                            text=content,
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                        )
                    )
                    await db.commit()
        else:
            await emit("error", {"message": "Run hit the max step limit."})

        await emit("run_finished", {})
    except asyncio.CancelledError:
        await emit("run_finished", {"cancelled": True})
        raise
    except Exception as e:  # noqa: BLE001 - surface any failure to the client
        await emit("error", {"message": str(e)[:2000]})
        await emit("run_finished", {"failed": True})


async def _execute_tool(tools, tool_call, session_id: str, user_id: str, emit) -> ToolResult:
    settings = get_settings()
    await emit(
        "tool_call_started",
        {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments},
    )
    tool = tools.get(tool_call.name)
    if tool is None:
        result = ToolResult(f"Unknown tool: {tool_call.name}", is_error=True)
    else:
        try:
            async with SessionLocal() as db:
                ctx = ToolContext(db=db, session_id=session_id, user_id=user_id, emit=emit)
                result = await asyncio.wait_for(
                    tool.execute(tool_call.arguments, ctx),
                    timeout=settings.tool_timeout_seconds,
                )
        except TimeoutError:
            result = ToolResult(
                f"Tool {tool_call.name} timed out after {settings.tool_timeout_seconds}s",
                is_error=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            result = ToolResult(f"Tool {tool_call.name} failed: {e}", is_error=True)
    await emit(
        "tool_result",
        {
            "id": tool_call.id,
            "name": tool_call.name,
            "content": result.content[:4000],
            "is_error": result.is_error,
            "metadata": result.metadata,
        },
    )
    return result
