from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.api import Limit, Problem
from app.auth.service import TenantSession

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])


class AlertOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class AlertList(BaseModel):
    items: list[AlertOut]


@router.get("", response_model=AlertList)
async def list_alerts(session: TenantSession, unread: bool = False, limit: Limit = 50) -> Any:
    """Newest first. ponytail: no cursor; the Today screen shows the latest few."""
    rows = await session.execute(
        text(
            "SELECT id, kind, title, body, read_at, created_at FROM alerts"
            + (" WHERE read_at IS NULL" if unread else "")
            + " ORDER BY id DESC LIMIT :n"
        ),
        {"n": limit},
    )
    return {"items": [dict(row._mapping) for row in rows]}


@router.post("/{alert_id}/read", status_code=204)
async def mark_read(alert_id: UUID, session: TenantSession) -> Response:
    """Idempotent: marking an already-read alert keeps its first read time."""
    found = await session.scalar(
        text("UPDATE alerts SET read_at = coalesce(read_at, now()) WHERE id = :id RETURNING id"),
        {"id": alert_id},
    )
    if found is None:
        raise Problem(404, "Alert not found.")
    return Response(status_code=204)
