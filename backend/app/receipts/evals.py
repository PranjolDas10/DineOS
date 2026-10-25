"""Receipt extraction eval harness. A CLI, never run in tests or CI: it calls the paid API.

    uv run python -m app.receipts.evals --tenant <id> --model claude-haiku-5-5 \\
        --model claude-sonnet-5-5 [--limit 50] --yes

Dataset = every confirmed receipt (receipt_labels): the original photo plus the
owner-confirmed truth. For each model it re-reads every photo and reports:
per-field accuracy, line recall/precision, cost per receipt, latency p50/p95, and a
confidence calibration table for choosing review.CONFIDENCE_THRESHOLD.
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app import storage
from app.db import SessionLocal, set_tenant
from app.receipts import extractor, service

# USD per million tokens (input, output), from Anthropic's price list on 2026-10-25.
# Update when prices change; cost numbers in old reports keep the prices they used.
PRICES = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
}
MATCH_RATIO = 0.6  # descriptions this similar are treated as the same line
RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _similar(a: Any, b: Any) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


@dataclass
class Score:
    header: dict[str, bool] = field(default_factory=dict)
    line_fields: dict[str, list[bool]] = field(default_factory=dict)
    matched: int = 0
    truth_lines: int = 0
    predicted_lines: int = 0
    # (model confidence, line fully correct) for every matched line: calibration data.
    calibration: list[tuple[float, bool]] = field(default_factory=list)


def score(truth: dict[str, Any], predicted: extractor.Extraction) -> Score:
    """Compare one extraction with the confirmed truth (receipt_labels.confirmed)."""
    s = Score(truth_lines=len(truth["lines"]), predicted_lines=len(predicted.lines))
    s.header = {
        "supplier_name": _similar(truth["supplier_name"], predicted.supplier_name) >= 0.9,
        "receipt_date": truth["receipt_date"] == predicted.receipt_date,
        "total_cents": truth["total_cents"] == predicted.total_cents,
    }
    # Greedy alignment: lines can be missed, added or reordered, so match each truth line
    # to the most similar unused predicted line.
    unused = list(predicted.lines)
    for t in truth["lines"]:
        best = max(unused, key=lambda p: _similar(t["description"], p.description), default=None)
        if best is None or _similar(t["description"], best.description) < MATCH_RATIO:
            continue
        unused.remove(best)
        s.matched += 1
        fields = {
            "description": _similar(t["description"], best.description) >= 0.9,
            "quantity": Decimal(str(t["quantity"])) == Decimal(str(best.quantity)),
            "line_total_cents": t["line_total_cents"] == best.line_total_cents,
        }
        for name, ok in fields.items():
            s.line_fields.setdefault(name, []).append(ok)
        s.calibration.append((best.confidence, all(fields.values())))
    return s


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def calibration_table(points: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    """For each candidate threshold: how many lines would skip review (confidence >= t),
    and how many of those would be wrong. Pick the lowest t with an acceptable error rate."""
    rows = []
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        auto = [ok for conf, ok in points if conf >= t]
        rows.append(
            {
                "threshold": t,
                "auto_accepted_pct": round(100 * len(auto) / len(points), 1) if points else None,
                "error_rate_pct": round(100 * auto.count(False) / len(auto), 1) if auto else None,
            }
        )
    return rows


def summarize(model: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[Score] = [r["score"] for r in runs]
    header = {
        name: _pct([s.header[name] for s in scores])
        for name in ("supplier_name", "receipt_date", "total_cents")
    }
    line_fields: dict[str, list[bool]] = {}
    for s in scores:
        for name, oks in s.line_fields.items():
            line_fields.setdefault(name, []).extend(oks)
    latencies = sorted(r["latency_s"] for r in runs)
    costs = [cost_usd(model, r["input_tokens"], r["output_tokens"]) for r in runs]
    return {
        "model": model,
        "prompt_version": extractor.PROMPT_VERSION,
        "receipts": len(runs),
        "failures": sum(r["failed"] for r in runs),
        "header_accuracy_pct": header,
        "line_field_accuracy_pct": {name: _pct(oks) for name, oks in line_fields.items()},
        "line_recall_pct": _ratio(
            sum(s.matched for s in scores), sum(s.truth_lines for s in scores)
        ),
        "line_precision_pct": _ratio(
            sum(s.matched for s in scores), sum(s.predicted_lines for s in scores)
        ),
        "cost_per_receipt_usd": str(sum(costs, Decimal(0)) / len(costs)) if costs else None,
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_s": round(latencies[int(0.95 * (len(latencies) - 1))], 2)
        if latencies
        else None,
        "calibration": calibration_table([p for s in scores for p in s.calibration]),
    }


def _pct(oks: list[bool]) -> float | None:
    return round(100 * sum(oks) / len(oks), 1) if oks else None


def _ratio(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


async def load_dataset(tenant: UUID, limit: int | None) -> list[dict[str, Any]]:
    async with SessionLocal() as session, session.begin():
        await set_tenant(session, tenant)
        rows = await session.execute(
            text(
                "SELECT r.object_key, l.confirmed::text AS confirmed FROM receipt_labels l"
                " JOIN receipts r ON r.id = l.receipt_id ORDER BY l.created_at"
                + (" LIMIT :n" if limit else "")
            ),
            {"n": limit} if limit else {},
        )
        return [{"key": r.object_key, "truth": json.loads(r.confirmed)} for r in rows]


async def run(tenant: UUID, models: list[str], limit: int | None) -> list[dict[str, Any]]:
    dataset = await load_dataset(tenant, limit)
    reports = []
    for model in models:
        runs = []
        for item in dataset:
            image = await asyncio.to_thread(storage.get_bytes, item["key"])
            started = time.perf_counter()
            try:
                result = await extractor.extract(image, service.media_type(item["key"]), model)
            except extractor.Unreadable:
                empty = extractor.Extraction(
                    supplier_name=None, receipt_date=None, total_cents=None, lines=[]
                )
                result = extractor.Result(empty, model, 0, 0)
                failed = True
            else:
                failed = False
            runs.append(
                {
                    "score": score(item["truth"], result.extraction),
                    "latency_s": time.perf_counter() - started,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "failed": failed,
                }
            )
        reports.append(summarize(model, runs))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--model", action="append", choices=sorted(PRICES), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true", help="confirm: this spends API credits")
    args = parser.parse_args()
    if not args.yes:
        parser.error("this calls the paid Claude API once per receipt per model; add --yes")
    reports = asyncio.run(run(args.tenant, args.model, args.limit))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"receipts-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports, indent=2))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
