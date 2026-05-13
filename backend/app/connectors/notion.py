"""Notion connector.

When ``MOCK_NOTION=1`` is set, the connector serves deterministic mock
pages — same testing posture as the Drive mock. The real OAuth path is
scaffolded: ``authorize_url`` and ``exchange_code`` follow Notion's API
shape, but the crawl methods refuse to fire against the real Notion API
until the implementation is hardened (see RUNBOOK).

OAuth scopes used (real path):
* ``read_content`` — page + database content
* ``read_user``    — identity bridge for the connecting user
* ``update_content`` — required for ``check_access`` page-retrieve probes
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from app.connectors import _notion_mock
from app.connectors.base import (
    CrawlerConnector,
    CrawlYield,
    CredentialBundle,
)
from app.connectors.registry import register
from app.core.config import get_settings

log = logging.getLogger(__name__)


_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
_TOKEN_URL = "https://api.notion.com/v1/oauth/token"


@register
class NotionConnector(CrawlerConnector):
    kind = "notion"
    display_name = "Notion"

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
        if get_settings().mock_notion:
            # The mock path uses the same callback URL with a stubbed
            # ``code`` value so the frontend doesn't branch.
            params = {
                "code": "mock-code",
                "state": state,
            }
            return f"{redirect_uri}?{urlencode(params)}"

        settings = get_settings()
        if not settings.notion_oauth_client_id:
            raise RuntimeError(
                "NOTION_OAUTH_CLIENT_ID is not configured; "
                "enable MOCK_NOTION for development."
            )
        params = {
            "client_id": settings.notion_oauth_client_id,
            "response_type": "code",
            "owner": "user",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        instance_id: str,
        code: str,
        redirect_uri: str,
    ) -> CredentialBundle:
        if get_settings().mock_notion:
            return _notion_mock.MOCK_BUNDLE

        settings = get_settings()
        if not (
            settings.notion_oauth_client_id
            and settings.notion_oauth_client_secret
        ):
            raise RuntimeError("Notion OAuth credentials not configured")
        # Real implementation: POST to _TOKEN_URL with Basic-Auth client
        # credentials and the code. Left as a stub here — the real call
        # uses httpx in the same shape as google_drive.exchange_code.
        raise NotImplementedError(
            "Real Notion OAuth exchange not yet implemented; "
            "set MOCK_NOTION=1 for development."
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
        if get_settings().mock_notion:
            for item in _notion_mock.initial_items():
                yield item
            return

        raise NotImplementedError(
            "Real Notion crawl not yet implemented; set MOCK_NOTION=1"
        )

    async def incremental_crawl(
        self,
        *,
        instance_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
        cursor: dict[str, Any] | None,
    ) -> AsyncIterator[CrawlYield]:
        if get_settings().mock_notion:
            tick = int((cursor or {}).get("tick", 0)) + 1
            for item in _notion_mock.incremental_items(tick):
                yield item
            return

        raise NotImplementedError(
            "Real Notion crawl not yet implemented; set MOCK_NOTION=1"
        )

    # ------------------------------------------------------------------
    # Source recheck
    # ------------------------------------------------------------------

    async def check_access(
        self,
        session,
        *,
        workspace_id: str,
        principal_user_id: str,
        source_ref: str,
    ) -> bool:
        """Live re-check against the Notion API.

        Mock mode always permits. Real mode is a stub today; high-
        sensitivity workspaces fail closed to match the Drive
        connector's behaviour rather than leaking by default.
        """
        if get_settings().mock_notion:
            return True

        # Real impersonation requires the Notion bot to be installed in
        # every workspace it inspects. Until that's wired up, follow the
        # same fail-closed-on-high-sensitivity rule as Drive.
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
        return not bool(row and row[0])
