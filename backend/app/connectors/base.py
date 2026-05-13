"""Connector base classes and value types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


ACLPrincipalKind = Literal["user", "group", "domain", "anyone"]


class ACLEntry(BaseModel):
    """One row of a source-system ACL.

    For 'anyone', ``external_id`` is None. For everything else it's the
    source-system identifier (Google ``sub`` or email for users, group
    id/email for groups, domain string for domains).

    ``role`` is informational only — visibility is binary in v1; we don't
    distinguish reader vs commenter vs writer for the ACL filter.
    """

    kind: ACLPrincipalKind
    external_id: str | None = None
    role: str | None = None


class CannedFact(BaseModel):
    """A pre-decided (subject, predicate, object) triple for mock crawls.

    Real connectors leave ``CrawledItem.canned_facts`` empty and let the
    LLM extraction pipeline derive facts from ``content``. Mock-mode
    connectors populate it so the demo works without API keys: the
    framework inserts these directly as edges with ``source_id`` set to
    the upserted episode.

    Subject and object resolve via ``app.connectors.canned.apply_canned_facts``:
    we look up by canonical name within the workspace, falling back to
    creating an entity of the requested type. Predicate must be an
    existing relation slug in the workspace's ontology (the seeded
    relations cover the common cases).
    """

    subject_canonical: str
    subject_type_slug: str
    predicate_slug: str
    object_canonical: str
    object_type_slug: str
    fact_text: str


class CrawledItem(BaseModel):
    """One source-system document the framework will upsert as an episode.

    ``content`` is the extracted plaintext (or markdown). Binary content
    must be extracted to text by the connector before yielding — the
    extraction pipeline expects ``episode.content_text``.

    ``external_revision_id`` is the connector-system change-detection
    primary key (Drive ``headRevisionId``, Confluence ``version.number``,
    etc.). When unavailable, set it to None and rely on ``content_hash``.

    ``canned_facts`` is non-empty for mock-mode crawls only — see
    ``CannedFact`` for the contract.
    """

    external_id: str
    external_url: str | None = None
    external_revision_id: str | None = None
    title: str
    mime_type: str | None = None
    content: str = Field(description="Extracted plaintext / markdown.")
    last_modified_external: datetime | None = None
    acl: list[ACLEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    canned_facts: list[CannedFact] = Field(default_factory=list)


class CredentialBundle(BaseModel):
    """Connector-specific credential payload.

    Flattened intentionally — we let each connector store whatever shape
    fits its OAuth flow. The framework encrypts the JSON-serialized form
    via pgcrypto on its way into ``connector_instance.credentials_encrypted``.
    """

    data: dict[str, Any]


class DeletedItem(BaseModel):
    """A connector signal that a previously-ingested document is gone.

    The framework soft-deletes the matching ``episode`` row.
    """

    external_id: str


CrawlYield = CrawledItem | DeletedItem


# ---------------------------------------------------------------------------
# Connector interface
# ---------------------------------------------------------------------------


class CrawlerConnector(ABC):
    """Base class for all source connectors.

    A connector is a stateless adapter: state (cursor, credentials) lives
    in the database on ``connector_instance``. The framework loads that
    row, calls into the connector's crawl methods, and persists results.
    """

    kind: ClassVar[str]
    """Stable identifier matching ``connector_instance.connector_kind``."""

    display_name: ClassVar[str]
    """Human-readable name (UI)."""

    # ------------------------------------------------------------------
    # OAuth / authorization
    # ------------------------------------------------------------------

    @abstractmethod
    async def authorize_url(
        self,
        *,
        instance_id: str,
        redirect_uri: str,
        state: str,
    ) -> str:
        """Return the URL to send the user to so they grant access.

        ``state`` is opaque to the connector — the framework signs and
        verifies it across the redirect to bind the callback to the
        originating request.
        """

    @abstractmethod
    async def exchange_code(
        self,
        *,
        instance_id: str,
        code: str,
        redirect_uri: str,
    ) -> CredentialBundle:
        """Exchange the OAuth code for tokens.

        Returned bundle is encrypted into
        ``connector_instance.credentials_encrypted`` by the framework.
        """

    # ------------------------------------------------------------------
    # Crawls
    # ------------------------------------------------------------------

    @abstractmethod
    async def initial_crawl(
        self,
        *,
        instance_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
        cursor: dict[str, Any] | None,
    ) -> AsyncIterator[CrawlYield]:
        """Yield every document (and ACL) accessible to the connector.

        Long-running. The framework persists ``cursor`` between batches
        so the job is resumable. ``cursor`` IS the connector's resume
        state — the framework treats it as opaque JSON.
        """

    @abstractmethod
    async def incremental_crawl(
        self,
        *,
        instance_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
        cursor: dict[str, Any] | None,
    ) -> AsyncIterator[CrawlYield]:
        """Yield documents that changed since the last cursor.

        For Drive: drives the change feed. For polling-style sources:
        re-list with a since-timestamp from the cursor.
        """

    # ------------------------------------------------------------------
    # ACL refresh (optional override)
    # ------------------------------------------------------------------

    async def fetch_acl(
        self,
        *,
        external_id: str,
        config: dict[str, Any],
        credentials: CredentialBundle,
    ) -> list[ACLEntry]:
        """Re-fetch ACL for one document.

        Default implementation raises NotImplementedError — connectors
        that don't support targeted ACL refresh fall back to running a
        full incremental_crawl.
        """
        raise NotImplementedError(
            f"{self.kind} connector does not support targeted ACL refresh"
        )

    # ------------------------------------------------------------------
    # Live-access check (high-sensitivity tenants, RFC §11.5)
    # ------------------------------------------------------------------

    async def check_access(
        self,
        session: Any,
        *,
        workspace_id: str,
        principal_user_id: str,
        source_ref: str,
    ) -> bool:
        """Verify the principal still has read access to ``source_ref``.

        Default permits access — only connectors implementing source-side
        impersonation should override. Implementations should return
        ``True`` on transient failures (caller treats this as best-effort
        belt-and-braces over the snapshot ACL).
        """
        return True
