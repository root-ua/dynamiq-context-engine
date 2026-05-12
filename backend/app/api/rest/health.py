from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import session_scope

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db() -> dict[str, str | int]:
    async with session_scope() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar_one()
    return {"status": "ok", "postgres": int(value)}
