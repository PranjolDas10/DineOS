from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from app import crud, jobs, storage
from app.api import Limit, Page, Problem, etag
from app.auth.service import Claims, TenantSession
from app.orders import service
from app.orders.models import Order, OrderItem, SalesImport

router = APIRouter(prefix="/v1", tags=["orders"])


class UploadUrlOut(BaseModel):
    object_key: str
    upload_url: str
    expires_in: int


class ImportCreate(BaseModel):
    id: UUID | None = None
    source: Annotated[str, StringConstraints(max_length=40)]  # a key of parsing.PROFILES
    object_key: Annotated[str, StringConstraints(max_length=200)]


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    status: str
    orders_new: int | None
    orders_updated: int | None
    duplicates: int | None
    error: str | None
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    external_id: str
    channel: str
    placed_at: datetime
    subtotal_cents: int
    tax_cents: int
    tip_cents: int
    total_cents: int


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    menu_item_id: UUID | None
    quantity: Decimal
    unit_price_cents: int
    line_total_cents: int


class OrderDetail(OrderOut):
    items: list[OrderItemOut]


class OrderList(BaseModel):
    items: list[OrderOut]


@router.post("/imports/upload-url", response_model=UploadUrlOut)
async def upload_url(claims: Claims) -> Any:
    """Step 1: upload the sales export (CSV) straight to storage with this URL."""
    key = service.new_object_key(claims["tid"])
    return {
        "object_key": key,
        "upload_url": storage.presign_put(key, "text/csv"),
        "expires_in": storage.UPLOAD_TTL_SECONDS,
    }


@router.post("/imports", status_code=201, response_model=ImportOut)
async def create_import(
    body: ImportCreate, claims: Claims, session: TenantSession, response: Response
) -> Any:
    """Step 2: register the upload; orders are imported in the background."""
    row = await service.create_import(session, claims["tid"], body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/imports", response_model=Page[ImportOut])
async def list_imports(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, SalesImport, cursor, limit)


@router.get("/imports/{import_id}", response_model=ImportOut)
async def get_import(import_id: UUID, session: TenantSession) -> Any:
    return await crud.get_or_404(session, SalesImport, import_id)


@router.get("/orders", response_model=OrderList)
async def list_orders(
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: TenantSession,
) -> Any:
    """The unified inbox: every channel's orders in one time window (max 31 days)."""
    if not timedelta(0) < end - start <= timedelta(days=31):
        raise Problem(422, "end must be after start, at most 31 days later.")
    stmt = (
        select(Order)
        .where(Order.placed_at >= start, Order.placed_at < end)
        .order_by(Order.placed_at.desc(), Order.id)
    )
    return {"items": list(await session.scalars(stmt))}


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(order_id: UUID, session: TenantSession) -> Any:
    order = await crud.get_or_404(session, Order, order_id)
    stmt = select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.position)
    items = list(await session.scalars(stmt))
    return {**OrderOut.model_validate(order).model_dump(), "items": items}


@router.post("/orders/replay", status_code=202)
async def replay(session: TenantSession) -> dict[str, Any]:
    """Rebuild all orders from the event log in the background (e.g. after renaming menu
    items, so old sales map to them)."""
    return {"job_id": await jobs.enqueue(session, "replay_orders", {})}
