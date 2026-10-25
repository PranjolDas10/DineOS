"""Receipt ingestion: register an uploaded photo, then parse it in a background job."""

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, jobs
from app.api import Problem
from app.config import settings
from app.receipts import extractor, storage
from app.receipts.models import Receipt, ReceiptLine

MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def new_object_key(tenant_id: str, content_type: str) -> str:
    """Keys are namespaced by tenant so a receipt can only point at its own tenant's uploads."""
    ext = next(e for e, mt in MEDIA_TYPES.items() if mt == content_type)
    return f"{tenant_id}/{uuid.uuid4()}.{ext}"


def media_type(object_key: str) -> str:
    return MEDIA_TYPES[object_key.rsplit(".", 1)[-1]]


async def create_receipt(session: AsyncSession, tenant_id: str, values: dict[str, Any]) -> Receipt:
    """Register an uploaded photo and enqueue its parse job in the same transaction."""
    key = values["object_key"]
    if not key.startswith(f"{tenant_id}/") or key.rsplit(".", 1)[-1] not in MEDIA_TYPES:
        raise Problem(422, "object_key must come from POST /v1/receipts/upload-url.")
    if "id" in values and (existing := await session.get(Receipt, values["id"])):
        return existing  # retried request: don't enqueue a second parse
    receipt = await crud.create(session, Receipt, values)
    await jobs.enqueue(session, "parse_receipt", {"receipt_id": str(receipt.id)})
    return receipt


@jobs.job("parse_receipt")
async def parse_receipt(session: AsyncSession, payload: dict[str, Any]) -> None:
    """Idempotent: re-running replaces this receipt's lines, and the cache makes the rerun free."""
    receipt = await session.get(Receipt, UUID(payload["receipt_id"]))
    if receipt is None or receipt.status == "confirmed":
        return  # gone, or already reviewed: never overwrite the owner's corrections
    image = await asyncio.to_thread(storage.get_bytes, receipt.object_key)
    try:
        result = await _extract_cached(session, image, media_type(receipt.object_key))
    except extractor.Unreadable as exc:
        receipt.status, receipt.failure_reason = "failed", str(exc)  # permanent: no retry
        return

    found = result.extraction
    await session.execute(delete(ReceiptLine).where(ReceiptLine.receipt_id == receipt.id))
    if found.lines:
        await session.execute(
            insert(ReceiptLine),
            [
                {
                    "receipt_id": receipt.id,
                    "position": i,
                    "description": line.description,
                    "quantity": Decimal(str(line.quantity)),  # via str: no binary-float digits
                    "unit": line.unit,
                    "unit_price_cents": line.unit_price_cents,
                    "line_total_cents": line.line_total_cents,
                    "confidence": Decimal(str(line.confidence)),
                }
                for i, line in enumerate(found.lines)
            ],
        )
    receipt.supplier_name = found.supplier_name
    receipt.receipt_date = _iso_date(found.receipt_date)
    receipt.total_cents = found.total_cents
    receipt.model, receipt.prompt_version = result.model, extractor.PROMPT_VERSION
    receipt.input_tokens, receipt.output_tokens = result.input_tokens, result.output_tokens
    receipt.status, receipt.failure_reason = "parsed", None
    receipt.version += 1
    receipt.updated_at = datetime.now(UTC)


async def _extract_cached(session: AsyncSession, image: bytes, mt: str) -> extractor.Result:
    key = {
        "h": hashlib.sha256(image).digest(),
        "m": settings.receipt_model,
        "v": extractor.PROMPT_VERSION,
    }
    cached = (
        await session.execute(
            text(
                "SELECT result::text AS result, input_tokens, output_tokens FROM extraction_cache"
                " WHERE content_sha256 = :h AND model = :m AND prompt_version = :v"
            ),
            key,
        )
    ).one_or_none()
    if cached is not None:
        found = extractor.Extraction.model_validate_json(cached.result)
        return extractor.Result(
            found, settings.receipt_model, cached.input_tokens, cached.output_tokens
        )

    result = await extractor.extract(image, mt, settings.receipt_model)
    await session.execute(
        text(
            "INSERT INTO extraction_cache"
            " (content_sha256, model, prompt_version, result, input_tokens, output_tokens)"
            " VALUES (:h, :m, :v, CAST(:r AS jsonb), :i, :o) ON CONFLICT DO NOTHING"
        ),
        {
            **key,
            "r": result.extraction.model_dump_json(),
            "i": result.input_tokens,
            "o": result.output_tokens,
        },
    )
    return result


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None  # unreadable date: leave it for the owner to fill in
