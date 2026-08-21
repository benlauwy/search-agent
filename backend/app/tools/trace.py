"""trace_session: inspect another session in this app by link or id.

Builds a structured transcript from persisted messages/files (never the live
event bus), so it reflects exactly what was stored. Access requires that the
caller owns the target session or that it is shared.
"""

import json
import re

from sqlalchemy import select

from ..models import ChatSession, File, Message
from .base import ToolContext, ToolResult

SESSION_ID_RE = re.compile(r"[0-9a-f]{32}")

MAX_TEXT_CHARS = 1500


def extract_session_id(url_or_id: str) -> str | None:
    match = SESSION_ID_RE.search(url_or_id.strip().lower())
    return match.group(0) if match else None


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


async def build_transcript(db, session: ChatSession) -> str:
    lines: list[str] = [
        f"# Session {session.id}",
        f"Title: {session.title}",
        f"Kind: {session.kind}"
        + (f" (parent: {session.parent_session_id})" if session.parent_session_id else ""),
        f"Provider: {session.provider}" + (f" · {session.model}" if session.model else ""),
        f"Created: {session.created_at.isoformat()}",
        "",
        "## Transcript",
    ]
    messages = (
        (
            await db.execute(
                select(Message).where(Message.session_id == session.id).order_by(Message.idx)
            )
        )
        .scalars()
        .all()
    )
    for m in messages:
        if m.role == "user":
            lines.append(f"[user] {_clip(m.text)}")
        elif m.role == "assistant":
            if m.text:
                lines.append(f"[assistant] {_clip(m.text)}")
            for tc in m.tool_calls_json or []:
                args = _clip(json.dumps(tc.get("arguments", {})), 300)
                lines.append(f"[assistant → tool_call] {tc.get('name')}({args})")
        elif m.role == "tool":
            lines.append(f"[tool_result: {m.tool_name}] {_clip(m.text, 800)}")

    files = (
        (
            await db.execute(
                select(File).where(File.session_id == session.id).order_by(File.created_at)
            )
        )
        .scalars()
        .all()
    )
    if files:
        lines.append("")
        lines.append("## Files")
        for f in files:
            lines.append(f"- {f.filename} (v{f.version}, {f.kind}, {f.size} bytes)")

    children = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.parent_session_id == session.id)
                .order_by(ChatSession.created_at)
            )
        )
        .scalars()
        .all()
    )
    if children:
        lines.append("")
        lines.append("## Subagent sessions")
        for c in children:
            lines.append(f"- {c.id}: {_clip(c.title, 120)}")
        lines.append("(Call trace_session with a subagent session id to inspect it.)")

    return "\n".join(lines)


class TraceSessionTool:
    name = "trace_session"
    description = (
        "Inspect another chat session in this app by its link or id. Returns a "
        "structured transcript: messages, tool calls and results (truncated), "
        "files, and any subagent sessions it spawned."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url_or_id": {
                "type": "string",
                "description": "A session link (e.g. .../#/sessions/<id>) or a raw session id",
            },
        },
        "required": ["url_or_id"],
    }
    timeout_seconds: int | None = None

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        session_id = extract_session_id(args["url_or_id"])
        if session_id is None:
            return ToolResult(
                "Could not find a session id in the input. Provide a session link or id.",
                is_error=True,
            )
        session = await ctx.db.get(ChatSession, session_id)
        if session is None or (session.user_id != ctx.user_id and not session.shared):
            return ToolResult(
                f"Session '{session_id}' not found or not accessible.", is_error=True
            )
        return ToolResult(await build_transcript(ctx.db, session))
