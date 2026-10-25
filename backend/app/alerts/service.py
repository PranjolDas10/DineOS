"""Public interface of the alerts module: anything that needs the owner's attention."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def notify(session: AsyncSession, kind: str, title: str, body: str) -> None:
    """Record an alert for the current tenant, in the caller's transaction.
    ponytail: in-app list only; FCM push delivery is added with the Android app."""
    await session.execute(
        text("INSERT INTO alerts (kind, title, body) VALUES (:k, :t, :b)"),
        {"k": kind, "t": title, "b": body},
    )
    log.info("alert %s: %s", kind, title)
