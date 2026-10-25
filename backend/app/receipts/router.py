from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from app import crud
from app.api import Limit, Page, etag
from app.auth.service import Claims, TenantSession
from app.receipts import service, storage
from app.receipts.models import Receipt, ReceiptLine

router = APIRouter(prefix="/v1/receipts", tags=["receipts"])


class UploadUrlIn(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class UploadUrlOut(BaseModel):
    object_key: str
    upload_url: str
    expires_in: int


class ReceiptCreate(BaseModel):
    id: UUID | None = None
    object_key: Annotated[str, StringConstraints(max_length=200)]


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    supplier_name: str | None
    receipt_date: date | None
    total_cents: int | None
    model: str | None
    prompt_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    failure_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    description: str
    quantity: Decimal
    unit: str
    unit_price_cents: int | None
    line_total_cents: int
    confidence: Decimal
    ingredient_id: UUID | None


class ReceiptDetail(ReceiptOut):
    lines: list[ReceiptLineOut]


@router.post("/upload-url", response_model=UploadUrlOut)
async def upload_url(body: UploadUrlIn, claims: Claims) -> Any:
    """Step 1: get a short-lived URL, then PUT the photo straight to storage with the same
    Content-Type. The API never handles image bytes."""
    key = service.new_object_key(claims["tid"], body.content_type)
    return {
        "object_key": key,
        "upload_url": storage.presign_put(key, body.content_type),
        "expires_in": storage.UPLOAD_TTL_SECONDS,
    }


@router.post("", status_code=201, response_model=ReceiptOut)
async def create_receipt(
    body: ReceiptCreate, claims: Claims, session: TenantSession, response: Response
) -> Any:
    """Step 2: after the upload succeeds, register it. Parsing starts in the background."""
    values = body.model_dump(exclude_none=True)
    row = await service.create_receipt(session, claims["tid"], values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("", response_model=Page[ReceiptOut])
async def list_receipts(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, Receipt, cursor, limit)


@router.get("/{receipt_id}", response_model=ReceiptDetail)
async def get_receipt(receipt_id: UUID, session: TenantSession, response: Response) -> Any:
    receipt = await crud.get_or_404(session, Receipt, receipt_id)
    stmt = select(ReceiptLine).where(ReceiptLine.receipt_id == receipt_id)
    lines = (await session.scalars(stmt.order_by(ReceiptLine.position))).all()
    response.headers["ETag"] = etag(receipt.version)
    return {**ReceiptOut.model_validate(receipt).model_dump(), "lines": lines}
