from __future__ import annotations

from dataclasses import asdict
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from app.api.rest.schemas import BlockTreeIn, DocumentCreate, DocumentOut
from app.auth.deps import CurrentPrincipal, DbSession
from app.core.logging import get_logger
from app.domain import document as doc_mod

router = APIRouter(prefix="/documents", tags=["documents"])

log = get_logger(__name__)

# Hard limit — avoid OOM on a surprise 100MB drop. 10 MB is enough for
# notes/markdown imports; larger files should go through a proper
# extraction pipeline once we build one.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# MIME types we know how to convert to a block tree directly. Binary
# formats (PDF, DOCX) get accepted as attachments but extraction is
# out of scope for this endpoint.
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
    document_id: str, _: CurrentPrincipal, session: DbSession
) -> DocumentOut:
    doc = await doc_mod.get_document(session, document_id)
    if not doc:
        raise HTTPException(404, "document not found")
    return DocumentOut(**asdict(doc))


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_doc(document_id: str, _: CurrentPrincipal, session: DbSession):
    await doc_mod.delete_document(session, document_id)


@router.get("/{document_id}/blocks")
async def get_blocks(
    document_id: str, _: CurrentPrincipal, session: DbSession
):
    blocks = await doc_mod.list_blocks(session, document_id=document_id)
    return [asdict(b) for b in blocks]


@router.put("/{document_id}/blocks")
async def replace_blocks(
    document_id: str,
    payload: BlockTreeIn,
    _: CurrentPrincipal,
    session: DbSession,
) -> dict[str, str]:
    await doc_mod.replace_block_tree(
        session,
        document_id=document_id,
        blocks=[b.model_dump() for b in payload.blocks],
    )
    return {"status": "ok"}


@router.post("/upload", status_code=201)
async def upload_document(
    principal: CurrentPrincipal,
    session: DbSession,
    file: UploadFile = File(...),
) -> DocumentOut:
    """Turn an uploaded text/markdown file into a new document.

    Binary formats (PDF, DOCX) return 415 for now. They should eventually
    flow through a proper extraction worker; wire that in once we build
    the ingestion pipeline.
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
                "only text and markdown files are supported for now. "
                "Binary extraction (PDF/DOCX) is not yet wired up."
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

    # Title: strip the extension and tidy whitespace.
    title = PurePosixPath(filename).stem.strip() or "Untitled"

    type_slug = "note" if suffix in {".md", ".markdown", ".mdx"} else "note"
    doc = await doc_mod.create_document(
        session,
        workspace_id=principal.workspace_id,
        title=title,
        type_slug=type_slug,
        created_by=principal.user_id,
    )

    # Split the body into paragraph blocks on blank-line boundaries. This
    # keeps the block tree readable when the doc opens in the editor;
    # the Yjs state is hydrated lazily on first edit.
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
