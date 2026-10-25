"""Receipt ingestion: presigned upload, register + enqueue, parse job (Claude faked)."""

import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.db import SessionLocal, set_tenant
from app.receipts import extractor, service, storage
from app.receipts.extractor import ExtractedLine, Extraction, Result, Unreadable
from tests.conftest import MakeTenant, auth_headers

pytestmark = pytest.mark.anyio

FAKE = Extraction(
    supplier_name="Restaurant Depot",
    receipt_date="2026-10-20",
    total_cents=8248,
    lines=[
        ExtractedLine(
            description="ONION YELLOW 50LB",
            quantity=1,
            unit="sack",
            unit_price_cents=3499,
            line_total_cents=3499,
            confidence=0.97,
        ),
        ExtractedLine(
            description="GHEE 1.6KG (smudged)",
            quantity=3,
            unit="jar",
            unit_price_cents=None,
            line_total_cents=4749,
            confidence=0.41,
        ),
    ],
)


@pytest.fixture
async def tenant(make_tenant: MakeTenant) -> tuple[UUID, dict[str, str]]:
    tenant_id = await make_tenant()
    return tenant_id, auth_headers(tenant_id)


@pytest.fixture
def fake_claude(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace storage + Claude. Returns the list of models called, to count real calls."""
    calls: list[str] = []

    async def fake_extract(image: bytes, media_type: str, model: str) -> Result:
        calls.append(model)
        return Result(FAKE, model, 1200, 300)

    monkeypatch.setattr(storage, "get_bytes", lambda key: b"fake image bytes")
    monkeypatch.setattr(extractor, "extract", fake_extract)
    return calls


async def register(client: AsyncClient, headers: dict[str, str], body: dict[str, Any]) -> Any:
    key = (
        await client.post(
            "/v1/receipts/upload-url", json={"content_type": "image/jpeg"}, headers=headers
        )
    ).json()["object_key"]
    resp = await client.post("/v1/receipts", json={"object_key": key, **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def run_parse(tenant_id: UUID, receipt_id: str) -> None:
    """Run the job handler directly (the queue mechanics are covered in test_jobs.py)."""
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        await service.parse_receipt(session, {"receipt_id": receipt_id})


async def test_upload_url_is_presigned_under_tenant_prefix(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    tenant_id, headers = tenant
    body = (
        await client.post(
            "/v1/receipts/upload-url", json={"content_type": "image/jpeg"}, headers=headers
        )
    ).json()
    assert body["object_key"].startswith(f"{tenant_id}/")
    assert body["object_key"].endswith(".jpg")
    assert f"/receipts/{body['object_key']}" in body["upload_url"]
    assert "X-Amz-Signature=" in body["upload_url"]


async def test_cannot_register_another_tenants_upload(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    _, headers = tenant
    stolen = f"{uuid.uuid4()}/someone-elses.jpg"
    resp = await client.post("/v1/receipts", json={"object_key": stolen}, headers=headers)
    assert resp.status_code == 422


async def test_register_enqueues_exactly_one_parse(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> None:
    tenant_id, headers = tenant
    receipt_id = str(uuid.uuid4())
    key = (
        await client.post(
            "/v1/receipts/upload-url", json={"content_type": "image/png"}, headers=headers
        )
    ).json()["object_key"]
    for _ in range(2):  # a retried request must not enqueue a second (paid) parse
        resp = await client.post(
            "/v1/receipts", json={"id": receipt_id, "object_key": key}, headers=headers
        )
        assert resp.status_code == 201
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        count = await session.scalar(
            text("SELECT count(*) FROM jobs WHERE payload->>'receipt_id' = :r"), {"r": receipt_id}
        )
    assert count == 1


async def test_parse_writes_lines_and_caches_by_content(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]], fake_claude: list[str]
) -> None:
    tenant_id, headers = tenant
    receipt = await register(client, headers, {})
    await run_parse(tenant_id, receipt["id"])

    got = (await client.get(f"/v1/receipts/{receipt['id']}", headers=headers)).json()
    assert got["status"] == "parsed"
    assert (got["supplier_name"], got["receipt_date"], got["total_cents"]) == (
        "Restaurant Depot",
        "2026-10-20",
        8248,
    )
    assert (got["input_tokens"], got["output_tokens"]) == (1200, 300)
    assert [(line["description"], line["confidence"]) for line in got["lines"]] == [
        ("ONION YELLOW 50LB", "0.97"),
        ("GHEE 1.6KG (smudged)", "0.41"),
    ]

    # A second run (job retry, or the same photo uploaded again) replaces, doesn't duplicate,
    # and is served from the cache: one paid call total.
    await run_parse(tenant_id, receipt["id"])
    again = (await client.get(f"/v1/receipts/{receipt['id']}", headers=headers)).json()
    assert len(again["lines"]) == 2
    assert fake_claude == ["claude-haiku-5-5"]


async def test_unreadable_receipt_fails_without_retry(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(image: bytes, media_type: str, model: str) -> Result:
        raise Unreadable("model stopped with max_tokens")

    monkeypatch.setattr(storage, "get_bytes", lambda key: b"blurry")
    monkeypatch.setattr(extractor, "extract", refuse)
    tenant_id, headers = tenant
    receipt = await register(client, headers, {})
    await run_parse(tenant_id, receipt["id"])  # returns normally: the job is done, not retried
    got = (await client.get(f"/v1/receipts/{receipt['id']}", headers=headers)).json()
    assert (got["status"], got["failure_reason"]) == ("failed", "model stopped with max_tokens")
