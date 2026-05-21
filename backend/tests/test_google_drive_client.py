"""Unit tests for the Google Drive HTTP client.

httpx is fully mocked — no network calls. Verifies:
- Pagination assembles all pages of list_children.
- Query string filters folders + Google Docs only.
- get_metadata returns parsed permissions.
- DriveAPIError raised on 4xx with Google's error message.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.integrations.google.drive_client import (
    DriveAPIError,
    DriveClient,
    MIME_FOLDER,
    MIME_GOOGLE_DOC,
)

pytestmark = pytest.mark.anyio


def _mock_response(status_code: int, body: Any, *, is_json: bool = True) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if is_json:
        resp.json = MagicMock(return_value=body)
        resp.text = "json"
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
        resp.text = body
    return resp


def _patch_http(client: DriveClient, monkeypatch, side_effect):
    """Replace the client's enter/exit with one that injects a mocked AsyncClient."""
    async def _enter(self):
        self._http = AsyncMock()
        self._http.get = AsyncMock(side_effect=side_effect)
        return self

    async def _exit(self, *a):
        self._http = None

    monkeypatch.setattr(DriveClient, "__aenter__", _enter)
    monkeypatch.setattr(DriveClient, "__aexit__", _exit)


async def test_list_children_paginates(monkeypatch):
    calls: list[dict[str, Any]] = []

    async def get(path: str, params=None):
        calls.append({"path": path, "params": params})
        # First page returns 2 items + nextPageToken. Second page returns 1 item.
        if not params.get("pageToken"):
            return _mock_response(200, {
                "files": [
                    {"id": "a", "name": "A.gdoc", "mimeType": MIME_GOOGLE_DOC, "modifiedTime": None},
                    {"id": "b", "name": "B", "mimeType": MIME_FOLDER, "modifiedTime": None},
                ],
                "nextPageToken": "PG2",
            })
        return _mock_response(200, {
            "files": [
                {"id": "c", "name": "C.gdoc", "mimeType": MIME_GOOGLE_DOC, "modifiedTime": None}
            ],
        })

    client = DriveClient("test-token")
    _patch_http(client, monkeypatch, side_effect=get)

    async with client as c:
        out = await c.list_children(folder_id="root")

    assert [n.id for n in out] == ["a", "b", "c"]
    assert len(calls) == 2
    # Query restricts to folder/google-doc + the right parent.
    first_q = calls[0]["params"]["q"]
    assert "'root' in parents" in first_q
    assert MIME_FOLDER in first_q
    assert MIME_GOOGLE_DOC in first_q


async def test_get_metadata_parses_permissions(monkeypatch):
    async def get(path: str, params=None):
        return _mock_response(200, {
            "id": "doc1",
            "name": "My Doc",
            "mimeType": MIME_GOOGLE_DOC,
            "modifiedTime": "2026-05-19T10:00:00Z",
            "headRevisionId": "rev-42",
            "permissions": [
                {"id": "p1", "type": "user", "role": "writer", "emailAddress": "alice@acme.com"},
                {"id": "p2", "type": "domain", "role": "reader", "domain": "acme.com"},
                {"id": "p3", "type": "anyone", "role": "reader"},
            ],
        })

    client = DriveClient("t")
    _patch_http(client, monkeypatch, side_effect=get)

    async with client as c:
        meta = await c.get_metadata("doc1")

    assert meta.id == "doc1"
    assert meta.head_revision_id == "rev-42"
    assert len(meta.permissions) == 3
    p_user = meta.permissions[0]
    assert p_user.type == "user" and p_user.email == "alice@acme.com"
    p_dom = meta.permissions[1]
    assert p_dom.type == "domain" and p_dom.domain == "acme.com"
    p_any = meta.permissions[2]
    assert p_any.type == "anyone"


async def test_4xx_raises_drive_api_error_with_message(monkeypatch):
    async def get(path: str, params=None):
        return _mock_response(403, {
            "error": {"code": 403, "message": "Insufficient Permission"}
        })

    client = DriveClient("t")
    _patch_http(client, monkeypatch, side_effect=get)

    with pytest.raises(DriveAPIError) as exc:
        async with client as c:
            await c.get_metadata("docX")

    assert exc.value.status == 403
    assert "Insufficient Permission" in exc.value.message
