"""Q4 — Governance chain.

Stresses the post-connector-removal stack: label assignment → policy
drop → admin bypass. (The high-sensitivity source-recheck step was
removed in Phase R because the platform no longer owns connectors.)
"""
from __future__ import annotations

import pytest

from app.auth.jwt import Principal
from app.db.session import session_scope
from app.domain import sensitivity as sens_mod

pytestmark = pytest.mark.scenario


def _principal(user, ws_id, *, role: str | None = None) -> Principal:
    return Principal(
        user_id=user.id, email=user.email,
        workspace_id=ws_id, role=role or user.role,
        claims={}, kind="user",
    )


@pytest.mark.asyncio
async def test_label_drop_for_editor_bypass_for_admin(enterprise_workspace):
    """Phase J3 + P5: label policy filters editor results, admin sees
    the same fact unfiltered."""
    e = enterprise_workspace
    ws_id = e.workspace_id

    async with session_scope(workspace_id=ws_id, user_id=e.alice.id) as s:
        from app.domain import episode as episode_mod
        ep = await episode_mod.add_episode(
            s, workspace_id=ws_id,
            content="Cross-tagged episode about governance Q4.",
            source_kind="agent", embed=False,
        )
        for slug in ("pii", "public"):
            await sens_mod.assign_label(
                s, workspace_id=ws_id, target_kind="episode",
                target_id=ep.id, label_slug=slug,
            )
        editor_kept, summary = await sens_mod.apply_label_policy(
            s, workspace_id=ws_id,
            candidates=[{"kind": "episode", "id": ep.id}],
            principal=_principal(e.alice, ws_id),
        )
        admin_kept, _ = await sens_mod.apply_label_policy(
            s, workspace_id=ws_id,
            candidates=[{"kind": "episode", "id": ep.id}],
            principal=_principal(e.admin, ws_id, role="admin"),
        )
    assert editor_kept == []
    assert summary["dropped"] == 1
    assert len(admin_kept) == 1
