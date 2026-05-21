"""Thin async wrapper around Google Drive v3 — only the calls the v1 sync needs.

Surfaces:
    list_root() / list_children(folder_id)  — for the picker UI
    get_metadata(file_id)                    — head_revision_id + permissions for sync state + ACL
    export_text(file_id)                     — Google Doc → plain text

Auth: callers pass in a refreshed access_token. Refresh is the caller's job
(see ``oauth.refresh_access_token``). This module is intentionally stateless
so refreshed tokens don't get stale-cached.

Pagination: list_children handles Drive's pageToken loop internally and returns
all children. For very large folders we could expose page_token; v1 doesn't need
that — Drive returns 100 entries/page so 1000-file folders cost 10 calls.

Errors: every Drive API call returns a parsed dict on 2xx, or raises
``DriveAPIError`` with the HTTP status + Google's error message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"

# Google Doc MIME types we care about for v1.
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_FOLDER = "application/vnd.google-apps.folder"

# Uploaded text formats we can text-extract via alt=media (no /export call).
MIME_TEXT_MARKDOWN = "text/markdown"
MIME_TEXT_PLAIN = "text/plain"

# All mime types we know how to pull text from. Used by the picker filter and
# by export_text to pick the right route (export vs alt=media).
TEXT_EXTRACTABLE_MIMES: tuple[str, ...] = (
    MIME_GOOGLE_DOC,
    MIME_TEXT_MARKDOWN,
    MIME_TEXT_PLAIN,
)

# Fields we ask Drive to return — avoid the default fields=* which is wasteful.
_METADATA_FIELDS = (
    "id,name,mimeType,modifiedTime,headRevisionId,owners(emailAddress),"
    "permissions(id,type,role,emailAddress,domain),parents"
)
_LIST_FIELDS = (
    "nextPageToken,files(id,name,mimeType,modifiedTime,headRevisionId)"
)


class DriveAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Drive API HTTP {status}: {message}")
        self.status = status
        self.message = message


@dataclass
class DriveNode:
    id: str
    name: str
    mime_type: str
    modified_time: datetime | None
    head_revision_id: str | None
    is_folder: bool
    is_doc: bool


@dataclass
class DrivePermission:
    """One ACE row from Drive's permissions list, normalized for ACL projection."""
    id: str
    role: str          # owner|organizer|fileOrganizer|writer|commenter|reader
    type: str          # user|group|domain|anyone
    email: str | None  # set when type ∈ {user, group}
    domain: str | None # set when type == domain


@dataclass
class DocMetadata:
    id: str
    name: str
    mime_type: str
    modified_time: datetime | None
    head_revision_id: str | None
    permissions: list[DrivePermission]


class DriveClient:
    """Use as `async with DriveClient(access_token) as client:`."""

    def __init__(self, access_token: str, *, timeout: float = 20.0):
        self._token = access_token
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "DriveClient":
        self._http = httpx.AsyncClient(
            base_url=DRIVE_API_BASE,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ----- Picker UI -----

    async def list_root(self) -> list[DriveNode]:
        """Top-level entries of "My Drive" (excludes Shared Drives — v1 scope)."""
        return await self.list_children(folder_id="root")

    async def list_children(self, *, folder_id: str) -> list[DriveNode]:
        """All children of one folder. Returns folders + Google Docs only for v1.

        We restrict the response with a Drive query so we don't list random
        binaries the integration can't extract text from anyway.
        """
        # Build the mime OR-list dynamically so adding a new extractable type
        # is one edit to TEXT_EXTRACTABLE_MIMES at module level.
        mime_clauses = [f"mimeType = '{MIME_FOLDER}'"] + [
            f"mimeType = '{m}'" for m in TEXT_EXTRACTABLE_MIMES
        ]
        q = (
            f"'{folder_id}' in parents and trashed = false and ("
            + " or ".join(mime_clauses)
            + ")"
        )
        out: list[DriveNode] = []
        page_token: str | None = None
        while True:
            params: dict[str, str | int] = {
                "q": q,
                "pageSize": 100,
                "fields": _LIST_FIELDS,
                "orderBy": "folder,name",
                "spaces": "drive",
            }
            if page_token:
                params["pageToken"] = page_token
            body = await self._get("/files", params=params)
            for f in body.get("files", []):
                out.append(_to_node(f))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return out

    # ----- Sync -----

    async def get_metadata(self, file_id: str) -> DocMetadata:
        """Return metadata + permission list for one file."""
        body = await self._get(
            f"/files/{file_id}",
            params={"fields": _METADATA_FIELDS, "supportsAllDrives": "false"},
        )
        perms_raw = body.get("permissions") or []
        permissions = [_to_permission(p) for p in perms_raw]
        return DocMetadata(
            id=body["id"],
            name=body.get("name", ""),
            mime_type=body.get("mimeType", ""),
            modified_time=_parse_dt(body.get("modifiedTime")),
            head_revision_id=body.get("headRevisionId"),
            permissions=permissions,
        )

    async def export_text(self, file_id: str, *, mime_type: str | None = None) -> str:
        """Return plain-text content of a Drive file.

        Routes by mime type:
        - Google-native Docs → GET /files/{id}/export?mimeType=text/plain
        - text/markdown, text/plain (uploaded files) → GET /files/{id}?alt=media

        ``mime_type`` is optional; when omitted we make a lightweight metadata
        call to discover it. Callers that already know the mime should pass it
        to save the round-trip.
        """
        assert self._http is not None

        if mime_type is None:
            meta = await self._get(
                f"/files/{file_id}",
                params={"fields": "mimeType"},
            )
            mime_type = meta.get("mimeType", "")

        if mime_type == MIME_GOOGLE_DOC:
            # GET /files/{fileId}/export?mimeType=text/plain
            resp = await self._http.get(
                f"/files/{file_id}/export",
                params={"mimeType": "text/plain"},
            )
            self._raise_for_status(resp)
            # Drive returns the file body directly, not JSON.
            return resp.text

        if mime_type in (MIME_TEXT_MARKDOWN, MIME_TEXT_PLAIN):
            # Uploaded text files don't support /export; use alt=media to grab
            # the raw bytes, then decode.
            resp = await self._http.get(
                f"/files/{file_id}",
                params={"alt": "media"},
            )
            self._raise_for_status(resp)
            data = resp.content
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode("latin-1")

        raise DriveAPIError(415, f"unsupported mime: {mime_type}")

    # ----- Internals -----

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self._http is not None
        resp = await self._http.get(path, params=params)
        self._raise_for_status(resp)
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            body = resp.json()
            err = body.get("error", {})
            msg = err.get("message") or resp.text[:200]
        except ValueError:
            msg = resp.text[:200]
        raise DriveAPIError(resp.status_code, msg)


# ----- Mappers -----


def _to_node(d: dict[str, Any]) -> DriveNode:
    mime = d.get("mimeType", "")
    return DriveNode(
        id=d["id"],
        name=d.get("name", ""),
        mime_type=mime,
        modified_time=_parse_dt(d.get("modifiedTime")),
        head_revision_id=d.get("headRevisionId"),
        is_folder=mime == MIME_FOLDER,
        # Any mime we can text-extract is a "leaf doc" for the picker UI —
        # the frontend renders these as files (not folders).
        is_doc=mime in TEXT_EXTRACTABLE_MIMES,
    )


def _to_permission(p: dict[str, Any]) -> DrivePermission:
    return DrivePermission(
        id=p.get("id", ""),
        role=p.get("role", "reader"),
        type=p.get("type", "user"),
        email=p.get("emailAddress"),
        domain=p.get("domain"),
    )


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # Drive returns RFC3339 with trailing Z; datetime.fromisoformat handles
    # the offset only in 3.11+.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
