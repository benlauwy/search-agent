import os
import re
import uuid

from sqlalchemy import select

from ..config import get_settings
from ..models import File
from .base import ToolContext, ToolResult

ALLOWED_ARTIFACT_EXTENSIONS = (".md", ".txt")


def _safe_filename(name: str) -> str:
    name = os.path.basename(name).strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name or "untitled.md"


def artifact_storage_path(file_id: str, filename: str) -> str:
    root = os.path.abspath(get_settings().data_dir)
    path = os.path.join(root, "files", f"{file_id}_{filename}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


class WriteFileTool:
    name = "write_file"
    description = (
        "Write a Markdown (.md) or plain text (.txt) file the user can download. "
        "Writing to an existing filename creates a new version."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "File name ending in .md or .txt"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["filename", "content"],
    }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        filename = _safe_filename(args["filename"])
        if not filename.lower().endswith(ALLOWED_ARTIFACT_EXTENSIONS):
            filename += ".md"
        content: str = args["content"]

        prev = await ctx.db.execute(
            select(File)
            .where(File.session_id == ctx.session_id, File.filename == filename)
            .order_by(File.version.desc())
            .limit(1)
        )
        prev_row = prev.scalar_one_or_none()
        version = (prev_row.version + 1) if prev_row else 1

        file_id = uuid.uuid4().hex
        path = artifact_storage_path(file_id, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        row = File(
            id=file_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            kind="artifact",
            filename=filename,
            mime="text/markdown" if filename.lower().endswith(".md") else "text/plain",
            size=len(content.encode()),
            version=version,
            path=path,
            extracted_text=content,
        )
        ctx.db.add(row)
        await ctx.db.commit()
        await ctx.emit(
            "artifact_created",
            {"file_id": file_id, "filename": filename, "version": version, "size": row.size},
        )
        return ToolResult(
            f"Wrote {filename} (version {version}, {row.size} bytes). "
            f"The user can download it from the artifacts panel.",
            metadata={"file_id": file_id},
        )


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a file uploaded to this session (or a previously written artifact). "
        "Large files are paginated; use offset to read more."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Name of the file to read"},
            "offset": {
                "type": "integer",
                "description": "Character offset to start reading from (default 0)",
            },
        },
        "required": ["filename"],
    }

    PAGE_CHARS = 15000

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        filename = args["filename"]
        result = await ctx.db.execute(
            select(File)
            .where(File.session_id == ctx.session_id, File.filename == filename)
            .order_by(File.version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            listing = await ctx.db.execute(
                select(File.filename).where(File.session_id == ctx.session_id).distinct()
            )
            names = [n for (n,) in listing.all()]
            available = ", ".join(names) if names else "(none)"
            return ToolResult(
                f"File '{filename}' not found. Available files: {available}", is_error=True
            )
        text = row.extracted_text or ""
        offset = max(int(args.get("offset") or 0), 0)
        page = text[offset : offset + self.PAGE_CHARS]
        remaining = len(text) - (offset + len(page))
        suffix = (
            f"\n\n[... {remaining} more characters; call read_file with offset="
            f"{offset + len(page)} to continue]"
            if remaining > 0
            else ""
        )
        header = f"{row.filename} (chars {offset}-{offset + len(page)} of {len(text)}):"
        return ToolResult(f"{header}\n{page}{suffix}")
