"""Deterministic stand-in for the Notion API.

Activated when ``MOCK_NOTION=1``. Mirrors ``_drive_mock`` in shape so the
test harness and demo flow exercise the same code path.

Three pages with distinct sharing models so the visibility matrix matches
the Drive mock:

* ``page-spec``     — workspace-public; everyone in the connecting
  user's workspace sees it.
* ``page-team``     — explicit per-user list (alice@acme.com).
* ``page-private``  — hr@acme.com only; no test user matches.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.connectors.base import (
    ACLEntry,
    CannedFact,
    CrawledItem,
    CredentialBundle,
    DeletedItem,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


MOCK_BUNDLE = CredentialBundle(
    data={
        "access_token": "mock-notion-token",
        "workspace_id": "mock-notion-workspace",
        "workspace_name": "Acme",
        "bot_id": "mock-bot",
        "scopes": ["read_content", "read_user", "update_content"],
        "expiry": "2099-01-01T00:00:00Z",
        "mock": True,
    }
)


_MOCK_PAGES = (
    {
        "id": "page-spec",
        "title": "Platform vision",
        "content": (
            "Dynamiq is building a permission-aware enterprise "
            "knowledge platform. This page describes the platform "
            "vision and the V1 milestones."
        ),
        "acl": [ACLEntry(kind="anyone", external_id="*", role="reader")],
        "facts": (
            CannedFact(
                subject_canonical="Dynamiq",
                subject_type_slug="organization",
                predicate_slug="builds",
                object_canonical="Knowledge platform",
                object_type_slug="project",
                fact_text="Dynamiq builds a knowledge platform.",
            ),
        ),
    },
    {
        "id": "page-team",
        "title": "Engineering standups",
        "content": (
            "Weekly engineering standups. Notes from the most "
            "recent meeting include the rollout plan for the Notion "
            "connector."
        ),
        "acl": [
            ACLEntry(kind="user", external_id="alice@acme.com", role="reader"),
        ],
        "facts": (),
    },
    {
        "id": "page-private",
        "title": "HR compensation review",
        "content": (
            "Confidential compensation review notes. Visible only to "
            "the HR partner."
        ),
        "acl": [
            ACLEntry(kind="user", external_id="hr@acme.com", role="reader"),
        ],
        "facts": (),
    },
)


def initial_items() -> list[CrawledItem]:
    out: list[CrawledItem] = []
    now = _now()
    for p in _MOCK_PAGES:
        out.append(
            CrawledItem(
                external_id=p["id"],
                title=p["title"],
                content=p["content"],
                mime_type="text/plain",
                external_url=f"https://www.notion.so/mock/{p['id']}",
                last_modified_external=now,
                acl=list(p["acl"]),
                metadata={"source": "notion", "kind": "page"},
                canned_facts=list(p["facts"]),
            )
        )
    return out


def incremental_items(tick: int) -> list[CrawledItem | DeletedItem]:
    """Returns a single edit on tick 1, nothing thereafter — keeps tests
    deterministic.
    """
    if tick != 1:
        return []
    now = _now()
    return [
        CrawledItem(
            external_id="page-spec",
            title="Platform vision (v2)",
            content=(
                "Dynamiq is building a permission-aware enterprise "
                "knowledge platform. V2 prioritises connector breadth "
                "and the kinetic action layer."
            ),
            mime_type="text/plain",
            external_url="https://www.notion.so/mock/page-spec",
            last_modified_external=now,
            acl=[ACLEntry(kind="anyone", external_id="*", role="reader")],
            metadata={"source": "notion", "kind": "page", "edit": True},
            canned_facts=[],
        )
    ]
