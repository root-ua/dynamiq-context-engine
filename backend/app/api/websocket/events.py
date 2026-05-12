"""WebSocket stream of workspace-scoped change events.

Client connects with ?token=<jwt>&workspace=<id>. Server LISTENs on
``workspace:<id>`` and forwards each notification to the client.
"""
from __future__ import annotations

import asyncio

import asyncpg
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth.jwt import AuthError, decode_token
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/events")
async def ws_events(
    websocket: WebSocket,
    token: str = Query(...),
    workspace: str = Query(...),
) -> None:
    await websocket.accept()

    try:
        principal = decode_token(token)
    except AuthError as exc:
        await websocket.send_json({"error": f"auth: {exc}"})
        await websocket.close(code=1008)
        return

    if principal.workspace_id and principal.workspace_id != workspace:
        await websocket.send_json({"error": "workspace mismatch"})
        await websocket.close(code=1008)
        return

    settings = get_settings()
    # asyncpg wants a raw DSN (not the +asyncpg SQLAlchemy URL).
    dsn = settings.postgres_url.replace("+asyncpg", "")

    conn: asyncpg.Connection | None = None
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)

    def on_notify(connection, pid, channel, payload) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # drop — UI should reconcile on refresh

    try:
        conn = await asyncpg.connect(dsn=dsn)
        channel = f"workspace:{workspace}"
        await conn.add_listener(channel, on_notify)

        await websocket.send_json({"connected": True, "channel": channel})

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30.0)
            except TimeoutError:
                await websocket.send_json({"ping": True})
                continue
            try:
                await websocket.send_text(payload)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        if conn is not None:
            try:
                await conn.remove_listener(f"workspace:{workspace}", on_notify)
            except Exception:
                pass
            try:
                await conn.close()
            except Exception:
                pass
