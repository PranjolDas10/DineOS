"""Receipt ingestion: presigned upload, register + enqueue, parse job (Claude faked)."""

import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app import storage
from app.db import SessionLocal, set_tenant
from app.receipts import extractor, service
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
    assert f"/uploads/{body['object_key']}" in body["upload_url"]
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


async def parsed(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]]
) -> tuple[dict[str, Any], str]:
    """A receipt that went through the (faked) parse job. Returns (detail, etag)."""
    tenant_id, headers = tenant
    receipt = await register(client, headers, {})
    await run_parse(tenant_id, receipt["id"])
    resp = await client.get(f"/v1/receipts/{receipt['id']}", headers=headers)
    return resp.json(), resp.headers["etag"]


def decisions(detail: dict[str, Any], onion_id: str | None) -> list[dict[str, Any]]:
    onion, ghee = detail["lines"]
    return [
        {
            "line_id": onion["id"],
            "ingredient_id": onion_id,
            "description": "ONION YELLOW 50LB",
            "quantity": "1",
            "unit": "sack",
            "line_total_cents": 3499,
            "base_qty": "22680",  # 50 lb in grams, converted by the UI
        },
        {  # skipped: not an ingredient we cost (and the owner fixes the smudged text)
            "line_id": ghee["id"],
            "ingredient_id": None,
            "description": "GHEE 1.6KG",
            "quantity": "3",
            "unit": "jar",
            "line_total_cents": 4749,
        },
    ]


async def test_confirm_writes_prices_and_eval_label(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]], fake_claude: list[str]
) -> None:
    tenant_id, headers = tenant
    onion = (
        await client.post(
            "/v1/ingredients", json={"name": "Onion", "base_unit": "g"}, headers=headers
        )
    ).json()["id"]
    supplier = (
        await client.post("/v1/suppliers", json={"name": "Restaurant Depot"}, headers=headers)
    ).json()["id"]
    detail, tag = await parsed(client, tenant)
    assert [line["needs_review"] for line in detail["lines"]] == [False, True]
    assert detail["photo_url"].startswith("http") and "Signature" in detail["photo_url"]

    body = {
        "supplier_id": supplier,
        "supplier_name": "Restaurant Depot",
        "receipt_date": "2026-10-20",
        "total_cents": 8248,
        "lines": decisions(detail, onion),
    }
    url = f"/v1/receipts/{detail['id']}/confirm"
    resp = await client.post(url, json=body, headers={**headers, "If-Match": tag})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"

    # The mapped line became a price observation dated by the receipt.
    price = (await client.get(f"/v1/ingredients/{onion}/prices", headers=headers)).json()["items"][
        0
    ]
    assert (price["pack_qty"], price["pack_price_cents"], price["supplier_id"]) == (
        "22680",
        3499,
        supplier,
    )
    assert price["observed_at"].startswith("2026-10-20")

    # Model output vs confirmed truth, ready for the eval harness.
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant_id)
        label = (
            await session.execute(
                text(
                    "SELECT model_output->'lines'->1->>'description',"
                    " confirmed->'lines'->1->>'description', model"
                    " FROM receipt_labels WHERE receipt_id = :r"
                ),
                {"r": detail["id"]},
            )
        ).one()
    assert tuple(label) == ("GHEE 1.6KG (smudged)", "GHEE 1.6KG", "claude-haiku-5-5")

    # A late parse retry must not overwrite the owner's corrections; confirming twice is a 409.
    await run_parse(tenant_id, detail["id"])
    after = await client.get(f"/v1/receipts/{detail['id']}", headers=headers)
    assert after.json()["lines"][1]["description"] == "GHEE 1.6KG"
    again = await client.post(
        url, json=body, headers={**headers, "If-Match": after.headers["etag"]}
    )
    assert again.status_code == 409


async def test_confirm_rejects_incomplete_or_stale_review(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]], fake_claude: list[str]
) -> None:
    _, headers = tenant
    detail, tag = await parsed(client, tenant)
    url = f"/v1/receipts/{detail['id']}/confirm"
    lines = decisions(detail, None)
    lines[0].pop("base_qty")

    skipped_one = {"lines": lines[:1]}  # the low-confidence line was never looked at
    resp = await client.post(url, json=skipped_one, headers={**headers, "If-Match": tag})
    assert resp.status_code == 422

    mapped_without_qty = decisions(detail, str(uuid.uuid4()))
    mapped_without_qty[0].pop("base_qty")
    resp = await client.post(
        url, json={"lines": mapped_without_qty}, headers={**headers, "If-Match": tag}
    )
    assert resp.status_code == 422

    stale = await client.post(url, json={"lines": lines}, headers={**headers, "If-Match": '"1"'})
    assert stale.status_code == 412


async def test_eval_harness_scores_confirmed_receipts(
    client: AsyncClient, tenant: tuple[UUID, dict[str, str]], fake_claude: list[str]
) -> None:
    """The label written at confirm time is exactly what the harness scores against."""
    from app.receipts import evals

    tenant_id, headers = tenant
    detail, tag = await parsed(client, tenant)
    lines = decisions(detail, None)
    lines[0].pop("base_qty")  # skip both lines: no ingredient mapping needed for the eval
    body = {
        "supplier_name": "Restaurant Depot",
        "receipt_date": "2026-10-20",
        "total_cents": 8248,
        "lines": lines,
    }
    resp = await client.post(
        f"/v1/receipts/{detail['id']}/confirm", json=body, headers={**headers, "If-Match": tag}
    )
    assert resp.status_code == 200, resp.text

    [report] = await evals.run(tenant_id, ["claude-haiku-5-5"], limit=None)
    assert report["receipts"] == 1
    assert report["header_accuracy_pct"] == {
        "supplier_name": 100.0,
        "receipt_date": 100.0,
        "total_cents": 100.0,
    }
    # The fake model misread the ghee line ("(smudged)" suffix); the owner fixed it.
    assert report["line_recall_pct"] == 100.0
    assert report["line_field_accuracy_pct"]["line_total_cents"] == 100.0
