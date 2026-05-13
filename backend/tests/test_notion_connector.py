"""Notion connector — registry + mock-mode crawls.

The real OAuth + crawl path is stubbed; this test verifies the framework
generalisation: the connector registers, its mock mode yields ``CrawledItem``
rows shaped exactly like Drive's, and its ``check_access`` short-circuits
under MOCK_NOTION.
"""
from __future__ import annotations

import os

import pytest

# Activate mock mode BEFORE the connector imports settings.
os.environ.setdefault("MOCK_NOTION", "1")

from app.connectors import registry  # noqa: E402
from app.connectors.base import CrawledItem  # noqa: E402


def test_notion_connector_registered():
    registry._import_connectors()
    cls = registry.get("notion")
    assert cls.kind == "notion"
    assert cls.display_name == "Notion"


@pytest.mark.asyncio
async def test_initial_crawl_yields_mock_pages():
    registry._import_connectors()
    connector = registry.get_connector("notion")
    yielded: list[CrawledItem] = []
    async for item in connector.initial_crawl(
        instance_id="t",
        config={},
        credentials=__import__(
            "app.connectors._notion_mock", fromlist=["MOCK_BUNDLE"]
        ).MOCK_BUNDLE,
        cursor=None,
    ):
        if isinstance(item, CrawledItem):
            yielded.append(item)
    titles = {it.title for it in yielded}
    assert "Platform vision" in titles
    assert "Engineering standups" in titles
    # Each page has at least one ACL entry.
    assert all(len(it.acl) >= 1 for it in yielded)


@pytest.mark.asyncio
async def test_incremental_crawl_emits_edit_on_tick_1():
    registry._import_connectors()
    connector = registry.get_connector("notion")
    items: list = []
    async for item in connector.incremental_crawl(
        instance_id="t",
        config={},
        credentials=__import__(
            "app.connectors._notion_mock", fromlist=["MOCK_BUNDLE"]
        ).MOCK_BUNDLE,
        cursor={"tick": 0},
    ):
        items.append(item)
    # Mock emits exactly one update on tick 1.
    assert len(items) == 1


@pytest.mark.asyncio
async def test_check_access_mock_short_circuits():
    registry._import_connectors()
    connector = registry.get_connector("notion")
    # No DB session needed in mock mode; passing None must not blow up.
    allowed = await connector.check_access(
        session=None,
        workspace_id="ws",
        principal_user_id="u",
        source_ref="page-spec",
    )
    assert allowed is True
