from __future__ import annotations

from dataclasses import asdict
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from app.api.rest.schemas import BlockTreeIn, DocumentCreate, DocumentOut
from app.auth.deps import CurrentPrincipal, DbSession
from app.core.logging import get_logger
from app.domain import document as doc_mod

router = APIRouter(prefix="/documents", tags=["documents"])

log = get_logger(__name__)


async def _require_doc_in_workspace(
    session, document_id: str, principal
):
    """Load a document and verify it belongs to the principal's workspace.

    Returns the document. Raises 404 if missing OR if it lives in a
    different workspace — we deliberately don't distinguish the two so
    the response doesn't leak which workspace a document id belongs to.
    """
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    doc = await doc_mod.get_document(session, document_id)
    if not doc or doc.workspace_id != principal.workspace_id:
        raise HTTPException(404, "document not found")
    return doc


# Hard limit — avoid OOM on a surprise 100MB drop. 10 MB is enough for
# the prose-document case.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Binary-format upload (PDF / DOCX / images) is the agent's job — Claude
# Code or the playground reads the file, extracts text, then calls
# ``add_episode`` via MCP. The web upload endpoint accepts already-text
# content (the block editor's source-of-truth shape).
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
    "application/x-markdown",
}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".mdx"}


@router.get("")
async def list_docs(
    principal: CurrentPrincipal,
    session: DbSession,
    query: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
) -> list[DocumentOut]:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    items = await doc_mod.list_documents(
        session, workspace_id=principal.workspace_id,
        query=query, limit=limit, offset=offset,
    )
    return [DocumentOut(**asdict(d)) for d in items]


@router.post("", status_code=201)
async def create(
    payload: DocumentCreate, principal: CurrentPrincipal, session: DbSession,
) -> DocumentOut:
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")
    doc = await doc_mod.create_document(
        session,
        workspace_id=principal.workspace_id,
        title=payload.title,
        type_slug=payload.type,
        props=payload.props,
        created_by=principal.user_id,
    )
    return DocumentOut(**asdict(doc))


@router.get("/{document_id}")
async def get_doc(
    document_id: str, principal: CurrentPrincipal, session: DbSession
) -> DocumentOut:
    doc = await _require_doc_in_workspace(session, document_id, principal)
    return DocumentOut(**asdict(doc))


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_doc(
    document_id: str, principal: CurrentPrincipal, session: DbSession
):
    await _require_doc_in_workspace(session, document_id, principal)
    await doc_mod.delete_document(session, document_id)


@router.get("/{document_id}/blocks")
async def get_blocks(
    document_id: str, principal: CurrentPrincipal, session: DbSession
):
    await _require_doc_in_workspace(session, document_id, principal)
    blocks = await doc_mod.list_blocks(session, document_id=document_id)
    return [asdict(b) for b in blocks]


@router.put("/{document_id}/blocks")
async def replace_blocks(
    document_id: str,
    payload: BlockTreeIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, str]:
    await _require_doc_in_workspace(session, document_id, principal)
    await doc_mod.replace_block_tree(
        session,
        document_id=document_id,
        blocks=[b.model_dump() for b in payload.blocks],
    )
    return {"status": "ok"}


@router.get("/{document_id}/revisions")
async def list_revisions(
    document_id: str, principal: CurrentPrincipal, session: DbSession
):
    await _require_doc_in_workspace(session, document_id, principal)
    return await doc_mod.list_revisions(session, document_id=document_id)


class _RevisionBody(BaseModel):
    note: str | None = None


@router.post("/{document_id}/revisions", status_code=201)
async def create_revision(
    document_id: str,
    body: _RevisionBody,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, str]:
    await _require_doc_in_workspace(session, document_id, principal)
    rid = await doc_mod.snapshot_revision(
        session,
        document_id=document_id,
        actor_id=principal.user_id,
        note=body.note,
    )
    return {"id": rid}


@router.post("/{document_id}/revisions/{revision_id}/restore")
async def restore_revision(
    document_id: str,
    revision_id: str,
    principal: CurrentPrincipal,
    session: DbSession,
) -> dict[str, str]:
    await _require_doc_in_workspace(session, document_id, principal)
    # The revision id also needs a workspace check so a caller can't
    # restore another workspace's revision into their own document.
    from sqlalchemy import text as _text

    rev_ws = (
        await session.execute(
            _text(
                "SELECT workspace_id::text FROM document_revision "
                "WHERE id = :id"
            ),
            {"id": revision_id},
        )
    ).scalar_one_or_none()
    if rev_ws != principal.workspace_id:
        raise HTTPException(404, "revision not found")

    try:
        await doc_mod.restore_revision(
            session,
            document_id=document_id,
            revision_id=revision_id,
            actor_id=principal.user_id,
        )
    except doc_mod.DocumentError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "restored"}


@router.post("/upload", status_code=201)
async def upload_document(
    principal: CurrentPrincipal,
    session: DbSession,
    file: UploadFile = File(...),
) -> DocumentOut:
    """Turn an uploaded text / markdown file into a new document.

    Binary formats (PDF, DOCX, etc.) are out of scope here — that's the
    calling agent's job. Claude Code reads the file, extracts text,
    and calls ``add_episode`` (MCP) with the resulting body; the
    platform handles the rest from there.
    """
    if not principal.workspace_id:
        raise HTTPException(400, "workspace required")

    filename = file.filename or "untitled"
    suffix = PurePosixPath(filename).suffix.lower()
    mime = (file.content_type or "").lower().split(";")[0].strip()

    is_text = mime in TEXT_MIME_TYPES or suffix in TEXT_EXTENSIONS
    if not is_text:
        raise HTTPException(
            status_code=415,
            detail=(
                "only text/markdown uploads are accepted here. "
                "For PDFs and other binary formats, have the agent "
                "(Claude Code, the playground) extract text and call "
                "the MCP `add_episode` tool."
            ),
        )

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )
    try:
        text_body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "file is not valid UTF-8 text") from exc

    title = PurePosixPath(filename).stem.strip() or "Untitled"
    _ = suffix
    type_slug = "note"
    doc = await doc_mod.create_document(
        session,
        workspace_id=principal.workspace_id,
        title=title,
        type_slug=type_slug,
        created_by=principal.user_id,
    )

    paragraphs = [p.strip() for p in text_body.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [""]
    blocks: list[dict[str, object]] = []
    for i, para in enumerate(paragraphs):
        blocks.append(
            {
                "id": str(uuid4()),
                "parent_block_id": None,
                "position": float(i),
                "block_type": "paragraph",
                "content": [{"type": "text", "text": para}],
                "props": {},
                "search_text": para,
            }
        )
    await doc_mod.replace_block_tree(
        session, document_id=doc.id, blocks=blocks
    )
    log.info(
        "document.upload",
        document_id=doc.id,
        filename=filename,
        bytes=len(raw),
        paragraphs=len(paragraphs),
    )
    return DocumentOut(**asdict(doc))
