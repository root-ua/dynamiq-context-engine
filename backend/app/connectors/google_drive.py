"""Google Drive connector.

When ``MOCK_DRIVE=1`` is set, falls back to deterministic mock data so
the entire installation → crawl → ACL → query loop runs without real
Google credentials. The mock path is what the E2E pytest suite and the
docker-compose demo use.

The real path uses ``google-api-python-client``. OAuth scopes:

* ``openid``, ``email``, ``profile`` — populates the identity bridge
  (so the connector installer's own identity gets resolved without an
  extra Connect-Google step)
* ``drive.readonly`` — file content + permissions

Per-file ACLs come from the Drive ``permissions.list`` API. We map them
to ``ACLEntry`` rows on the way into ``episode_acl``. The visibility
filter (in ``app/auth/acl.py``) takes care of resolving them against
each user's ``user_external_identity`` at query time.
"""
from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from app.connectors import _drive_mock
from app.connectors.base import (
    ACLEntry,
    CrawledItem,
    CrawlerConnector,
    CrawlYield,
    CredentialBundle,
    DeletedItem,
)
from app.connectors.registry import register
from app.core.config import get_settings

log = logging.getLogger(__name__)


# Mime types we ingest. Workspace types get exported to text; PDFs and
# plain text are downloaded directly.
_INGESTIBLE_MIME_TYPES = (
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/pdf",
    "text/plain",
    "text/markdown",
)

_EXPORT_MIME_FOR = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

_MAX_BYTES = 5 * 1024 * 1024  # 5MB content cap; bigger files skipped with a warning


@register
class GoogleDriveConnector(CrawlerConnector):
    kind = "google_drive"
    display_name = "Google Drive"

    async def check_access(
        self,
        session,
        *,
        workspace_id: str,
        principal_user_id: str,
        source_ref: str,
    ) -> bool:
        """Live re-check that the user still has read access to a Drive
        file.

        Behavior:
        * **Mock mode** (``MOCK_DRIVE=1``) — always returns True; the
          mock ACL snapshot is the test contract.
        * **High-sensitivity workspace, no bridged Google identity** —
          returns False. The whole point of the high-sensitivity flag
          is to fail closed when we can't independently confirm access.
        * **Standard workspace, no bridged identity** — returns True;
          the snapshot ACL already gated the fact.
        * **Bridged identity present** — currently returns True (real
          ``files.get`` via domain-wide delegation is a follow-up).
        """
        if get_settings().mock_drive:
            return True

        from sqlalchemy import text as _text
        row = (
            await session.execute(
                _text(
                    """
                    SELECT uei.external_id, uei.external_email
                    FROM user_external_identity uei
                    WHERE uei.user_id = CAST(:u AS uuid)
                      AND uei.workspace_id = CAST(:w AS uuid)
                      AND uei.provider = 'google'
                    LIMIT 1
                    """
                ),
                {"u": principal_user_id, "w": workspace_id},
            )
        ).first()
        if not row:
            # No bridged identity. High-sensitivity workspaces fail
            # closed; the rest fall back to the snapshot ACL.
            return not await _is_high_sensitivity(session, workspace_id)
        # TODO: real Drive ``files.get`` impersonation via
        # domain-wide delegation. For now the snapshot ACL is
        # authoritative.
        return True

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    async def authorize_url(
        self,
        *,
        instance_id: str,
        redirect_uri: str,
        state: str,
    ) -> str:
        if get_settings().mock_drive:
            # In mock mode we still send the user through the same callback
            # URL so the frontend code path is identical to real OAuth —
            # the callback handler just receives ``code=mock-code``.
            return f"{redirect_uri}?{urlencode({'code': 'mock-code', 'state': state})}"

        settings = get_settings()
        client_id = settings.google_oauth_client_id
        if not client_id:
            raise RuntimeError(
                "GOOGLE_OAUTH_CLIENT_ID is not configured; cannot start Drive OAuth"
            )
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(
                [
                    "openid",
                    "email",
                    "profile",
                    "https://www.googleapis.com/auth/drive.readonly",
                ]
            ),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        instance_id: str,
        code: str,
        redirect_uri: str,
    ) -> CredentialBundle:
        if get_settings().mock_drive or code == "mock-code":
            return _drive_mock.MOCK_BUNDLE

        # Real path uses google-auth-oauthlib. We import lazily so the
        # tests / mock path don't pay the dependency cost when the
        # package isn't installed.
        from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]

        settings = get_settings()
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
            redirect_uri=redirect_uri,
        )
        # Run the network-bound exchange in a thread so we don't block
        # the event loop.
        await asyncio.to_thread(flow.fetch_token, code=code)
        creds = flow.credentials
        return CredentialBundle(
            data={
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or []),
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
            }
        )

    # ------------------------------------------------------------------
    # Crawls
    # ------------------------------------------------------------------

    async def initial_crawl(
        self,
        *,
        instance_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
        cursor: dict[str, Any] | None,
    ) -> AsyncIterator[CrawlYield]:
        if get_settings().mock_drive or credentials.data.get("mock"):
            for item in _drive_mock.initial_items():
                yield item
            return

        async for item in self._real_initial_crawl(credentials, cursor or {}):
            yield item

    async def incremental_crawl(
        self,
        *,
        instance_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
        cursor: dict[str, Any] | None,
    ) -> AsyncIterator[CrawlYield]:
        if get_settings().mock_drive or credentials.data.get("mock"):
            tick = (cursor or {}).get("mock_tick", 0)
            for item in _drive_mock.incremental_items(tick):
                yield item
            return

        async for item in self._real_incremental_crawl(credentials, cursor or {}):
            yield item

    async def fetch_acl(
        self,
        *,
        external_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
    ) -> list[ACLEntry]:
        if get_settings().mock_drive or credentials.data.get("mock"):
            for item in _drive_mock.initial_items():
                if item.external_id == external_id:
                    return list(item.acl)
            return []

        service = await asyncio.to_thread(_build_drive_service, credentials)
        return await asyncio.to_thread(
            _fetch_acl_sync, service, external_id
        )

    # ------------------------------------------------------------------
    # Real Drive paths (real OAuth + Google API)
    # ------------------------------------------------------------------

    async def _real_initial_crawl(
        self,
        credentials: CredentialBundle,
        cursor: dict[str, Any],
    ) -> AsyncIterator[CrawlYield]:
        service = await asyncio.to_thread(_build_drive_service, credentials)
        page_token = cursor.get("page_token")
        mime_q = " or ".join(f"mimeType='{m}'" for m in _INGESTIBLE_MIME_TYPES)

        while True:
            response = await asyncio.to_thread(
                _list_files_page,
                service,
                page_token=page_token,
                q=f"({mime_q}) and trashed=false",
            )
            for f in response.get("files", []):
                try:
                    item = await asyncio.to_thread(_fetch_item_sync, service, f)
                    if item is not None:
                        yield item
                except Exception as exc:
                    log.warning(
                        "drive.fetch_item_failed file_id=%s err=%s", f.get("id"), exc
                    )
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # End of crawl — capture the start token for incremental.
        start = await asyncio.to_thread(
            lambda: service.changes().getStartPageToken().execute()
        )
        cursor["change_token"] = start.get("startPageToken")

    async def _real_incremental_crawl(
        self,
        credentials: CredentialBundle,
        cursor: dict[str, Any],
    ) -> AsyncIterator[CrawlYield]:
        service = await asyncio.to_thread(_build_drive_service, credentials)
        page_token = cursor.get("change_token")
        if not page_token:
            return

        while True:
            response = await asyncio.to_thread(
                lambda: service.changes()
                .list(
                    pageToken=page_token,
                    fields=(
                        "nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,file("
                        "id,name,mimeType,modifiedTime,headRevisionId,webViewLink"
                        "))"
                    ),
                )
                .execute()
            )
            for change in response.get("changes", []):
                if change.get("removed"):
                    yield DeletedItem(external_id=change["fileId"])
                    continue
                f = change.get("file") or {}
                if f.get("mimeType") not in _INGESTIBLE_MIME_TYPES:
                    continue
                try:
                    item = await asyncio.to_thread(_fetch_item_sync, service, f)
                    if item is not None:
                        yield item
                except Exception as exc:
                    log.warning(
                        "drive.fetch_change_failed file_id=%s err=%s",
                        f.get("id"),
                        exc,
                    )
            if response.get("newStartPageToken"):
                cursor["change_token"] = response["newStartPageToken"]
                break
            if response.get("nextPageToken"):
                page_token = response["nextPageToken"]
                continue
            break


# ---------------------------------------------------------------------------
# Real Drive helpers (sync; wrapped with asyncio.to_thread by the connector)
# ---------------------------------------------------------------------------


def _build_drive_service(credentials: CredentialBundle):
    from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    data = credentials.data
    expiry = data.get("expiry")
    expiry_dt: datetime | None = None
    if expiry:
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            expiry_dt = None

    creds = Credentials(
        token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or [],
        expiry=expiry_dt.replace(tzinfo=None) if expiry_dt else None,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_files_page(service, *, page_token: str | None, q: str) -> dict:
    return (
        service.files()
        .list(
            q=q,
            pageSize=100,
            pageToken=page_token,
            corpora="user",
            fields=(
                "nextPageToken, files("
                "id,name,mimeType,modifiedTime,headRevisionId,webViewLink"
                ")"
            ),
            supportsAllDrives=False,
        )
        .execute()
    )


def _fetch_item_sync(service, f: dict) -> CrawledItem | None:
    """Pull content + ACL for one Drive file. Returns None on cap exceeded."""
    mime = f.get("mimeType")
    file_id = f["id"]
    content = _fetch_content_sync(service, file_id, mime)
    if content is None:
        return None
    acl = _fetch_acl_sync(service, file_id)
    modified_iso = f.get("modifiedTime")
    last_modified: datetime | None = None
    if modified_iso:
        try:
            last_modified = datetime.fromisoformat(modified_iso.replace("Z", "+00:00"))
        except ValueError:
            last_modified = None

    return CrawledItem(
        external_id=file_id,
        external_url=f.get("webViewLink"),
        external_revision_id=f.get("headRevisionId"),
        title=f.get("name", ""),
        mime_type=mime,
        content=content,
        last_modified_external=last_modified,
        acl=acl,
        metadata={"source": "google_drive"},
    )


def _fetch_content_sync(service, file_id: str, mime: str | None) -> str | None:
    from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]

    if mime in _EXPORT_MIME_FOR:
        export_mime = _EXPORT_MIME_FOR[mime]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id)

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if buf.tell() > _MAX_BYTES:
            log.warning("drive.content_capped file_id=%s", file_id)
            return None

    raw = buf.getvalue()
    if mime == "application/pdf":
        return _extract_pdf_text(raw)
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        log.warning("drive.pdf_skipped reason=pypdf_not_installed")
        return ""
    reader = PdfReader(io.BytesIO(raw))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(parts)


def _fetch_acl_sync(service, file_id: str) -> list[ACLEntry]:
    response = (
        service.permissions()
        .list(
            fileId=file_id,
            fields=(
                "permissions(id,type,emailAddress,domain,role,deleted)"
            ),
            supportsAllDrives=False,
        )
        .execute()
    )
    out: list[ACLEntry] = []
    for p in response.get("permissions", []):
        if p.get("deleted"):
            continue
        ptype = p.get("type")
        role = p.get("role")
        if ptype == "user":
            email = p.get("emailAddress")
            if email:
                out.append(ACLEntry(kind="user", external_id=email, role=role))
            pid = p.get("id")
            if pid and pid != email:
                out.append(ACLEntry(kind="user", external_id=pid, role=role))
        elif ptype == "group":
            email = p.get("emailAddress")
            if email:
                out.append(ACLEntry(kind="group", external_id=email, role=role))
        elif ptype == "domain":
            domain = p.get("domain")
            if domain:
                out.append(ACLEntry(kind="domain", external_id=domain, role=role))
        elif ptype == "anyone":
            out.append(ACLEntry(kind="anyone", external_id=None, role=role))
    return out


async def _is_high_sensitivity(session, workspace_id: str) -> bool:
    """Read the ``high_sensitivity`` flag for fail-closed source recheck."""
    from sqlalchemy import text as _text

    row = (
        await session.execute(
            _text(
                "SELECT high_sensitivity FROM workspace "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": workspace_id},
        )
    ).first()
    return bool(row and row[0])


def _now() -> datetime:
    return datetime.now(tz=UTC)
