"""spawn_subagents: run N child agents in parallel.

Each child is a real session (kind="subagent", hidden from the session list)
with its own messages and events, so it is inspectable via trace_session and
the trace UI. Children run with the parent's provider, the configured subagent
model, and a restricted toolset (no spawn_subagents — depth 1). Concurrency
and per-child step budgets are bounded.
"""

import asyncio
import math

from ..config import get_settings
from ..models import ChatSession, Message
from .base import ToolContext, ToolResult

MAX_ANSWER_CHARS = 4000


class _SubagentTimeout(Exception):
    pass


class SpawnSubagentsTool:
    name = "spawn_subagents"
    description = (
        "Run several sub-tasks in parallel, each handled by an independent "
        "subagent with web search and file tools. Use for research that splits "
        "into independent parts. Returns each subagent's final answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "Sub-tasks to run in parallel (each becomes one subagent)",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "What the subagent should do"},
                        "context": {
                            "type": "string",
                            "description": "Optional extra context for the subagent",
                        },
                    },
                    "required": ["task"],
                },
            },
        },
        "required": ["tasks"],
    }

    def __init__(self):
        # subagent_timeout_seconds bounds each child individually (see run_one).
        # The outer tool timeout only guards the worst case: all task batches
        # running back-to-back at the configured concurrency, plus slack.
        s = get_settings()
        batches = math.ceil(s.max_subagents / s.subagent_concurrency)
        self.timeout_seconds: int | None = batches * s.subagent_timeout_seconds + 60

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from ..agent import runner  # deferred: runner imports the tool registry

        settings = get_settings()
        tasks = args.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return ToolResult("'tasks' must be a non-empty array.", is_error=True)
        if len(tasks) > settings.max_subagents:
            return ToolResult(
                f"Too many tasks: {len(tasks)} (max {settings.max_subagents}).", is_error=True
            )

        parent = await ctx.db.get(ChatSession, ctx.session_id)
        children: list[tuple[str, str]] = []  # (child_session_id, task_text)
        for t in tasks:
            task_text = str(t.get("task", "")).strip()
            if not task_text:
                return ToolResult("Every task needs a non-empty 'task' string.", is_error=True)
            context = str(t.get("context", "")).strip()
            prompt = task_text if not context else f"{task_text}\n\nContext:\n{context}"
            child = ChatSession(
                user_id=ctx.user_id,
                title=task_text[:80],
                provider=parent.provider,
                kind="subagent",
                parent_session_id=parent.id,
            )
            ctx.db.add(child)
            await ctx.db.flush()
            ctx.db.add(Message(session_id=child.id, idx=0, role="user", text=prompt))
            children.append((child.id, task_text))
        await ctx.db.commit()

        sem = asyncio.Semaphore(settings.subagent_concurrency)

        async def run_one(child_id: str, task_text: str) -> str | None:
            async with sem:
                await ctx.emit(
                    "subagent_started", {"session_id": child_id, "task": task_text}
                )
                timed_out = False
                try:
                    answer = await asyncio.wait_for(
                        runner.run_subagent(child_id, ctx.user_id),
                        timeout=settings.subagent_timeout_seconds,
                    )
                except TimeoutError:
                    answer = None
                    timed_out = True
                await ctx.emit(
                    "subagent_finished",
                    {
                        "session_id": child_id,
                        "ok": answer is not None,
                        "timed_out": timed_out,
                    },
                )
                if timed_out:
                    raise _SubagentTimeout(
                        f"timed out after {settings.subagent_timeout_seconds}s"
                    )
                return answer

        gathered = await asyncio.gather(
            *[run_one(cid, task) for cid, task in children], return_exceptions=True
        )

        sections: list[str] = []
        any_ok = False
        for (child_id, task_text), outcome in zip(children, gathered, strict=True):
            header = f"## Subagent {child_id} — {task_text[:120]}"
            if isinstance(outcome, BaseException):
                if isinstance(outcome, asyncio.CancelledError):
                    raise outcome
                sections.append(f"{header}\nFailed: {str(outcome)[:500]}")
            elif outcome is None:
                sections.append(f"{header}\nFailed: the subagent run did not produce an answer.")
            else:
                any_ok = True
                answer = outcome
                if len(answer) > MAX_ANSWER_CHARS:
                    answer = answer[:MAX_ANSWER_CHARS] + "... [truncated]"
                sections.append(f"{header}\n{answer}")
        sections.append(
            "(Each subagent is a session; use trace_session with its id for full details.)"
        )
        return ToolResult("\n\n".join(sections), is_error=not any_ok)
