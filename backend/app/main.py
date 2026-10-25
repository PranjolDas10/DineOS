from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.router import router as alerts_router
from app.api import install_problem_handlers
from app.auth.router import router as auth_router
from app.checklists.router import router as checklists_router
from app.config import settings
from app.db import engine, get_session
from app.inventory.router import router as inventory_router
from app.menu.router import router as menu_router
from app.observability import RequestContext, setup_logging, start_metrics_server
from app.receipts.router import router as receipts_router
from app.scheduling.router import router as scheduling_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    start_metrics_server(settings.metrics_port)  # internal port, never the public API
    yield
    await engine.dispose()


app = FastAPI(title="DineOS", lifespan=lifespan)
install_problem_handlers(app)
app.add_middleware(RequestContext)
app.include_router(auth_router)
app.include_router(inventory_router)
app.include_router(menu_router)
app.include_router(receipts_router)
app.include_router(scheduling_router)
app.include_router(checklists_router)
app.include_router(alerts_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(session: Annotated[AsyncSession, Depends(get_session)]) -> JSONResponse:
    """Readiness: can serve traffic, i.e. the database answers."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
