"""Deterministic stand-in for the Google Drive API.

Activated when ``MOCK_DRIVE=1`` so the full installation + crawl + ACL
loop can run without real Google OAuth credentials. Used both by the
pytest E2E suite and by the docker-compose demo.

Three documents with deliberately different ACL shapes so the visibility
matrix is meaningful:

* ``alpha-shared``  — domain-shared with ``acme.com``: anyone with an
  acme.com identity sees it.
* ``bravo-team``    — explicit per-user list: alice@acme.com,
  carol@acme.com.
* ``charlie-private`` — explicit per-user list: hr@acme.com only. No
  test user matches; only admins should see it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.connectors.base import (
    ACLEntry,
    CannedFact,
    CrawledItem,
    CredentialBundle,
    DeletedItem,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# Mock OAuth bundle returned from exchange_code in mock mode. The shape
# matches what google.oauth2.credentials.Credentials expects, so the real
# code path that materializes credentials still works (no None-checks).
MOCK_BUNDLE = CredentialBundle(
    data={
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "mock-client-id",
        "client_secret": "mock-client-secret",
        "scopes": [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "expiry": "2099-01-01T00:00:00Z",
        "mock": True,
    }
)


@dataclass(frozen=True)
class _MockDoc:
    external_id: str
    title: str
    content: str
    acl: list[ACLEntry]
    facts: list[CannedFact]


_MOCK_DOCS: list[_MockDoc] = [
    _MockDoc(
        external_id="alpha-shared",
        title="Q3 OKRs",
        content=(
            "Q3 engineering OKRs:\n"
            "- Ship the Drive connector\n"
            "- Hit p95 search latency under 500ms\n"
            "- Onboard the first enterprise customer."
        ),
        acl=[ACLEntry(kind="domain", external_id="acme.com", role="reader")],
        # Visible to anyone with an acme.com identity — the broad-membership
        # baseline plus the org-level OKR topic.
        facts=[
            CannedFact(
                subject_canonical="Engineering",
                subject_type_slug="organization",
                predicate_slug="member_of",
                object_canonical="Acme",
                object_type_slug="organization",
                fact_text="Engineering is part of Acme.",
            ),
            CannedFact(
                subject_canonical="Alice",
                subject_type_slug="person",
                predicate_slug="member_of",
                object_canonical="Engineering",
                object_type_slug="organization",
                fact_text="Alice is on the Engineering team.",
            ),
            CannedFact(
                subject_canonical="Bob",
                subject_type_slug="person",
                predicate_slug="member_of",
                object_canonical="Engineering",
                object_type_slug="organization",
                fact_text="Bob is on the Engineering team.",
            ),
            CannedFact(
                subject_canonical="Carol",
                subject_type_slug="person",
                predicate_slug="member_of",
                object_canonical="Engineering",
                object_type_slug="organization",
                fact_text="Carol is on the Engineering team.",
            ),
            CannedFact(
                subject_canonical="Engineering",
                subject_type_slug="organization",
                predicate_slug="tagged",
                object_canonical="Q3 OKRs",
                object_type_slug="topic",
                fact_text="Engineering owns the Q3 OKRs.",
            ),
        ],
    ),
    _MockDoc(
        external_id="bravo-team",
        title="Backend Roadmap (Eng leads)",
        content=(
            "Internal roadmap. Alice owns the connector framework. "
            "Carol owns the ACL filter design. Bob is on call this rotation."
        ),
        acl=[
            ACLEntry(kind="user", external_id="alice@acme.com", role="writer"),
            ACLEntry(kind="user", external_id="carol@acme.com", role="reader"),
        ],
        # Visible only to alice@acme.com and carol@acme.com — the
        # per-person ownership facts that prove the ACL filter is alive.
        facts=[
            CannedFact(
                subject_canonical="Alice",
                subject_type_slug="person",
                predicate_slug="tagged",
                object_canonical="Connector framework",
                object_type_slug="topic",
                fact_text="Alice owns the connector framework.",
            ),
            CannedFact(
                subject_canonical="Carol",
                subject_type_slug="person",
                predicate_slug="tagged",
                object_canonical="ACL filter design",
                object_type_slug="topic",
                fact_text="Carol owns the ACL filter design.",
            ),
            CannedFact(
                subject_canonical="Bob",
                subject_type_slug="person",
                predicate_slug="tagged",
                object_canonical="On-call rotation",
                object_type_slug="topic",
                fact_text="Bob is on the on-call rotation.",
            ),
        ],
    ),
    _MockDoc(
        external_id="charlie-private",
        title="Compensation review",
        content=(
            "Confidential HR memo. David's promotion to Staff Engineer is "
            "effective next quarter."
        ),
        acl=[ACLEntry(kind="user", external_id="hr@acme.com", role="reader")],
        facts=[
            CannedFact(
                subject_canonical="David",
                subject_type_slug="person",
                predicate_slug="tagged",
                object_canonical="Staff Engineer promotion",
                object_type_slug="topic",
                fact_text="David is being promoted to Staff Engineer.",
            ),
        ],
    ),
]


def initial_items() -> list[CrawledItem]:
    """Items yielded by ``GoogleDriveConnector.initial_crawl`` in mock mode."""
    now = _now()
    return [
        CrawledItem(
            external_id=d.external_id,
            external_url=f"https://docs.example/{d.external_id}",
            external_revision_id=f"rev-1-{d.external_id}",
            title=d.title,
            mime_type="application/vnd.google-apps.document",
            content=d.content,
            last_modified_external=now,
            acl=list(d.acl),
            metadata={"mock": True},
            canned_facts=list(d.facts),
        )
        for d in _MOCK_DOCS
    ]


def incremental_items(tick: int) -> list[CrawledItem | DeletedItem]:
    """Items yielded by ``GoogleDriveConnector.incremental_crawl``.

    ``tick=0`` (the first incremental call after the initial crawl) yields
    nothing — there's been no change yet.

    ``tick=1`` yields a synthetic edit of ``alpha-shared`` so the diff
    path through ``upsert_item`` is exercised by the E2E test. The
    revision id is bumped so ``content_changed`` flips to True.

    ``tick=2`` yields a deletion of ``charlie-private``.

    Subsequent ticks yield nothing.
    """
    if tick == 1:
        edited = _MOCK_DOCS[0]
        return [
            CrawledItem(
                external_id=edited.external_id,
                external_url=f"https://docs.example/{edited.external_id}",
                external_revision_id=f"rev-2-{edited.external_id}",
                title=edited.title,
                mime_type="application/vnd.google-apps.document",
                content=edited.content + "\n\nUPDATE: shipped on schedule.",
                last_modified_external=_now(),
                acl=list(edited.acl),
                metadata={"mock": True, "edited": True},
            )
        ]
    if tick == 2:
        return [DeletedItem(external_id="charlie-private")]
    return []
