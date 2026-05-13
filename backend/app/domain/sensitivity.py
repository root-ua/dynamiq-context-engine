"""Sensitivity labels + label-combination policy (RFC-001 §11.4).

Three concerns:

1. CRUD on ``sensitivity_label`` — typed labels with an ``ltree`` path
   for parent/child relations (mirrors entity_type subtyping).
2. Assignment of labels to episodes / edges (many-to-many).
3. Policy evaluation: given a query result set and a principal,
   filter (drop), warn, or block based on declarative rules.

Rule grammar lives in ``label_policy.rule`` (jsonb). The shapes we
support today:

* ``{"kind": "mutually_exclusive", "labels": ["pii","marketing"]}``
  — drop any candidate that carries two labels from the set on the
  same context.
* ``{"kind": "requires_role", "labels": ["confidential"], "roles": ["admin","owner"]}``
  — drop candidates carrying these labels unless the principal's
  workspace role is in ``roles``.

Adding a new rule kind is a 5-line ``elif`` block in
``apply_label_policy``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import Principal
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class Label:
    id: str
    workspace_id: str
    slug: str
    name: str
    description: str | None
    color: str | None
    path: str
    created_at: str
    updated_at: str


@dataclass
class Policy:
    id: str
    workspace_id: str
    name: str
    rule: dict[str, Any]
    action: str  # 'drop' | 'warn' | 'block'
    enabled: bool


# ---------------------------------------------------------------------------
# Label CRUD
# ---------------------------------------------------------------------------

async def create_label(
    session: AsyncSession,
    *,
    workspace_id: str,
    slug: str,
    name: str,
    description: str | None = None,
    color: str | None = None,
    parent_slug: str | None = None,
) -> Label:
    parent_path: str | None = None
    if parent_slug:
        row = (
            await session.execute(
                text(
                    """
                    SELECT path::text FROM sensitivity_label
                    WHERE workspace_id = :ws AND slug = :slug
                    """
                ),
                {"ws": workspace_id, "slug": parent_slug},
            )
        ).first()
        if row:
            parent_path = row[0]
    path = f"{parent_path}.{_ltree_safe(slug)}" if parent_path else _ltree_safe(slug)

    row = (
        await session.execute(
            text(
                """
                INSERT INTO sensitivity_label
                  (workspace_id, slug, name, description, color, path)
                VALUES (:ws, :slug, :name, :desc, :color, CAST(:path AS ltree))
                RETURNING id::text, workspace_id::text, slug, name, description,
                          color, path::text,
                          created_at::text, updated_at::text
                """
            ),
            {
                "ws": workspace_id,
                "slug": slug,
                "name": name,
                "desc": description,
                "color": color,
                "path": path,
            },
        )
    ).mappings().first()
    assert row is not None
    return _row_to_label(row)


async def list_labels(
    session: AsyncSession, *, workspace_id: str
) -> list[Label]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, slug, name, description,
                       color, path::text,
                       created_at::text, updated_at::text
                FROM sensitivity_label
                WHERE workspace_id = :ws
                ORDER BY path
                """
            ),
            {"ws": workspace_id},
        )
    ).mappings().all()
    return [_row_to_label(r) for r in rows]


async def get_label(
    session: AsyncSession, *, workspace_id: str, slug: str
) -> Label | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id::text, workspace_id::text, slug, name, description,
                       color, path::text,
                       created_at::text, updated_at::text
                FROM sensitivity_label
                WHERE workspace_id = :ws AND slug = :slug
                """
            ),
            {"ws": workspace_id, "slug": slug},
        )
    ).mappings().first()
    return _row_to_label(row) if row else None


async def delete_label(
    session: AsyncSession, *, workspace_id: str, slug: str
) -> bool:
    result = await session.execute(
        text(
            """
            DELETE FROM sensitivity_label
            WHERE workspace_id = :ws AND slug = :slug
            """
        ),
        {"ws": workspace_id, "slug": slug},
    )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

# Mapping from public ``target_kind`` to the (label table, FK column) pair.
# Defined once so the assign/unassign/labels_for/policy paths can't drift
# (and so the whitelist check lives in exactly one place).
_LABEL_TABLES: dict[str, tuple[str, str]] = {
    "episode": ("episode_label", "episode_id"),
    "edge": ("edge_label", "edge_id"),
}


def _resolve_label_table(target_kind: str) -> tuple[str, str]:
    if target_kind not in _LABEL_TABLES:
        raise ValueError(f"invalid target_kind: {target_kind}")
    return _LABEL_TABLES[target_kind]


async def assign_label(
    session: AsyncSession,
    *,
    workspace_id: str,
    target_kind: str,
    target_id: str,
    label_slug: str,
    assigned_by: str | None = None,
) -> None:
    table, target_col = _resolve_label_table(target_kind)
    label = await get_label(session, workspace_id=workspace_id, slug=label_slug)
    if not label:
        raise ValueError(f"label not found: {label_slug}")

    await session.execute(
        text(
            f"""
            INSERT INTO {table}
              ({target_col}, label_id, workspace_id, assigned_by)
            VALUES (:tid, :lid, :ws, :ab)
            ON CONFLICT DO NOTHING
            """
        ),
        {"tid": target_id, "lid": label.id, "ws": workspace_id, "ab": assigned_by},
    )


async def unassign_label(
    session: AsyncSession,
    *,
    workspace_id: str,
    target_kind: str,
    target_id: str,
    label_slug: str,
) -> bool:
    table, target_col = _resolve_label_table(target_kind)
    label = await get_label(session, workspace_id=workspace_id, slug=label_slug)
    if not label:
        return False
    result = await session.execute(
        text(f"DELETE FROM {table} WHERE {target_col} = :tid AND label_id = :lid"),
        {"tid": target_id, "lid": label.id},
    )
    return result.rowcount > 0


async def labels_for(
    session: AsyncSession,
    *,
    target_kind: str,
    target_id: str,
) -> list[Label]:
    table, target_col = _resolve_label_table(target_kind)
    rows = (
        await session.execute(
            text(
                f"""
                SELECT sl.id::text, sl.workspace_id::text, sl.slug, sl.name,
                       sl.description, sl.color, sl.path::text,
                       sl.created_at::text, sl.updated_at::text
                FROM {table} m
                JOIN sensitivity_label sl ON sl.id = m.label_id
                WHERE m.{target_col} = :tid
                ORDER BY sl.path
                """
            ),
            {"tid": target_id},
        )
    ).mappings().all()
    return [_row_to_label(r) for r in rows]


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------

async def create_policy(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    rule: dict[str, Any],
    action: str,
    enabled: bool = True,
) -> Policy:
    import json
    if action not in ("drop", "warn", "block"):
        raise ValueError(f"invalid action: {action}")
    row = (
        await session.execute(
            text(
                """
                INSERT INTO label_policy
                  (workspace_id, name, rule, action, enabled)
                VALUES (:ws, :name, CAST(:rule AS jsonb), :action, :enabled)
                RETURNING id::text, workspace_id::text, name, rule, action, enabled
                """
            ),
            {
                "ws": workspace_id,
                "name": name,
                "rule": json.dumps(rule),
                "action": action,
                "enabled": enabled,
            },
        )
    ).mappings().first()
    assert row is not None
    return _row_to_policy(row)


async def list_policies(
    session: AsyncSession, *, workspace_id: str, enabled_only: bool = False
) -> list[Policy]:
    where = "workspace_id = :ws"
    if enabled_only:
        where += " AND enabled = TRUE"
    rows = (
        await session.execute(
            text(
                f"""
                SELECT id::text, workspace_id::text, name, rule, action, enabled
                FROM label_policy
                WHERE {where}
                ORDER BY created_at DESC
                """
            ),
            {"ws": workspace_id},
        )
    ).mappings().all()
    return [_row_to_policy(r) for r in rows]


async def delete_policy(
    session: AsyncSession, *, policy_id: str
) -> bool:
    result = await session.execute(
        text("DELETE FROM label_policy WHERE id = :id"),
        {"id": policy_id},
    )
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

@dataclass
class LabelDecision:
    """The verdict for a single candidate item against the active rules."""

    keep: bool
    warnings: list[str]
    blocked_by: list[str]  # policy names that triggered a block


async def apply_label_policy(
    session: AsyncSession,
    *,
    workspace_id: str,
    candidates: list[dict[str, Any]],
    principal: Principal | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run enabled label policies over ``candidates``.

    ``candidates`` is a list of dicts each containing at minimum::

        {"kind": "edge"|"episode", "id": str}

    The function reads the assigned labels for the relevant ids in one
    batched query, evaluates the active rules, and returns ``(kept,
    summary)``. ``summary`` reports counts plus the names of policies
    that caused drops/warnings — useful for the "N results filtered by
    label policy" banner in the UI.

    Admin / owner / service principals **bypass** every policy, matching
    the bypass shape in :func:`app.auth.acl._bypasses_acl`. The two
    governance layers must agree, otherwise "make me admin" stops
    unlocking what users expect.
    """
    if not candidates:
        return candidates, {"dropped": 0, "warned": 0, "policies": []}

    # Bypass for admins, owners, and service-kind callers. Set
    # ``policy_warnings = []`` on every kept candidate so the shape
    # matches the non-bypass path — callers that do
    # ``c["policy_warnings"]`` instead of ``c.get(...)`` don't KeyError.
    if principal is not None and (
        principal.kind == "service"
        or (principal.role in ("owner", "admin"))
    ):
        for c in candidates:
            c.setdefault("policy_warnings", [])
        return candidates, {"dropped": 0, "warned": 0, "policies": []}

    policies = await list_policies(
        session, workspace_id=workspace_id, enabled_only=True
    )
    if not policies:
        return candidates, {"dropped": 0, "warned": 0, "policies": []}

    edge_ids = [c["id"] for c in candidates if c.get("kind") == "edge"]
    episode_ids = [c["id"] for c in candidates if c.get("kind") == "episode"]

    labels_by_target: dict[tuple[str, str], set[str]] = {}
    if edge_ids:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT m.edge_id::text AS tid, sl.slug
                    FROM edge_label m
                    JOIN sensitivity_label sl ON sl.id = m.label_id
                    WHERE m.edge_id = ANY(:ids)
                    """
                ),
                {"ids": edge_ids},
            )
        ).mappings().all()
        for r in rows:
            labels_by_target.setdefault(("edge", r["tid"]), set()).add(r["slug"])
    if episode_ids:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT m.episode_id::text AS tid, sl.slug
                    FROM episode_label m
                    JOIN sensitivity_label sl ON sl.id = m.label_id
                    WHERE m.episode_id = ANY(:ids)
                    """
                ),
                {"ids": episode_ids},
            )
        ).mappings().all()
        for r in rows:
            labels_by_target.setdefault(("episode", r["tid"]), set()).add(r["slug"])

    kept: list[dict[str, Any]] = []
    triggered_policies: set[str] = set()
    dropped = 0
    warned = 0

    role = principal.role if principal else None

    for c in candidates:
        target_key = (c.get("kind") or "", c.get("id") or "")
        labels = labels_by_target.get(target_key, set())
        drop = False
        warnings: list[str] = []

        for p in policies:
            rule = p.rule or {}
            kind = rule.get("kind")
            if kind == "mutually_exclusive":
                wanted = set(rule.get("labels") or [])
                hit = labels & wanted
                if len(hit) >= 2:
                    triggered_policies.add(p.name)
                    if p.action == "drop":
                        drop = True
                    elif p.action == "warn":
                        warnings.append(p.name)
                    elif p.action == "block":
                        drop = True  # 'block' surfaces as drop here; UI shows banner
            elif kind == "requires_role":
                if labels & set(rule.get("labels") or []):
                    allowed = set(rule.get("roles") or [])
                    if not role or role not in allowed:
                        triggered_policies.add(p.name)
                        if p.action == "drop":
                            drop = True
                        elif p.action == "warn":
                            warnings.append(p.name)
                        elif p.action == "block":
                            drop = True

        if drop:
            dropped += 1
            continue
        if warnings:
            warned += 1
            c.setdefault("policy_warnings", []).extend(warnings)
        kept.append(c)

    return kept, {
        "dropped": dropped,
        "warned": warned,
        "policies": sorted(triggered_policies),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_label(row: Any) -> Label:
    return Label(
        id=row["id"],
        workspace_id=row["workspace_id"],
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        color=row.get("color"),
        path=row["path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_policy(row: Any) -> Policy:
    return Policy(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        rule=row["rule"] or {},
        action=row["action"],
        enabled=bool(row["enabled"]),
    )


def _ltree_safe(slug: str) -> str:
    """ltree labels accept [A-Za-z0-9_]; replace anything else with underscores."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in slug)
