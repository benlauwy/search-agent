import contextlib
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.routes import get_current_user
from ..config import get_settings
from ..db import get_db
from ..models import ChatSession, File, User
from ..tools.files import (
    _safe_filename,
    artifact_storage_path,
    file_version_lock,
    next_file_version,
)
from .sessions import get_owned_session

router = APIRouter(prefix="/api", tags=["files"])

# Content-aware upload support: text-only for now. Future formats (images,
# Word docs, PDFs) plug in as additional extractors keyed by MIME type.
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIMES = {
    "application/json",
    "application/xml",
    "application/x-yaml",
    "application/javascript",
}
TEXT_EXTENSIONS = (
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".py", ".js", ".ts", ".log",
)


def _is_supported_text(filename: str, content_type: str | None) -> bool:
    if content_type:
        if content_type.split(";")[0].strip() in TEXT_MIMES:
            return True
        if content_type.startswith(TEXT_MIME_PREFIXES):
            return True
    return filename.lower().endswith(TEXT_EXTENSIONS)


def _file_dict(f: File) -> dict:
    return {
        "id": f.id,
        "kind": f.kind,
        "filename": f.filename,
        "mime": f.mime,
        "size": f.size,
        "version": f.version,
        "created_at": f.created_at.isoformat(),
    }


@router.get("/sessions/{session_id}/files")
async def list_files(
    session: ChatSession = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(File).where(File.session_id == session.id).order_by(File.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_file_dict(f) for f in rows]


@router.post("/sessions/{session_id}/files")
async def upload_file(
    file: UploadFile,
    session: ChatSession = Depends(get_owned_session),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    filename = _safe_filename(file.filename or "upload.txt")
    if not _is_supported_text(filename, file.content_type):
        raise HTTPException(
            415,
            "Unsupported file type. Only text files (e.g. .txt, .md, .csv, .json) "
            "are supported for now.",
        )
    # Read in bounded chunks so oversized uploads are rejected before the
    # whole body is materialized in memory.
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(65536):
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise HTTPException(413, f"File too large (max {settings.max_upload_bytes} bytes)")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(415, "File is not valid UTF-8 text") from e

    file_id = uuid.uuid4().hex
    path = artifact_storage_path(file_id, filename)
    with open(path, "wb") as f:
        f.write(raw)

    try:
        async with file_version_lock:
            row = File(
                id=file_id,
                session_id=session.id,
                user_id=user.id,
                kind="upload",
                filename=filename,
                mime=file.content_type or "text/plain",
                size=len(raw),
                version=await next_file_version(db, session.id, filename),
                path=path,
                extracted_text=text,
            )
            db.add(row)
            await db.commit()
    except BaseException:
        # The row never landed, so the on-disk file would be unreachable.
        with contextlib.suppress(OSError):
            os.unlink(path)
        raise
    return _file_dict(row)


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(File, file_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "File not found")
    return FileResponse(row.path, filename=row.filename, media_type=row.mime)
