"""Eval scoring is pure logic: tested here without a DB or the API."""

from decimal import Decimal
from typing import Any

from app.receipts.evals import calibration_table, cost_usd, score, summarize
from app.receipts.extractor import ExtractedLine, Extraction

TRUTH: dict[str, Any] = {
    "supplier_name": "Restaurant Depot",
    "receipt_date": "2026-10-20",
    "total_cents": 8248,
    "lines": [
        {"description": "ONION YELLOW 50LB", "quantity": "1", "line_total_cents": 3499},
        {"description": "GHEE 1.6KG", "quantity": "3", "line_total_cents": 4749},
    ],
}


def line(description: str, quantity: float, total: int, confidence: float) -> ExtractedLine:
    return ExtractedLine(
        description=description,
        quantity=quantity,
        unit="each",
        unit_price_cents=None,
        line_total_cents=total,
        confidence=confidence,
    )


def test_perfect_extraction_scores_everything_correct() -> None:
    predicted = Extraction(
        supplier_name="RESTAURANT DEPOT",  # case and spacing don't count as errors
        receipt_date="2026-10-20",
        total_cents=8248,
        lines=[  # order doesn't matter: lines are aligned by description
            line("GHEE 1.6KG", 3, 4749, 0.9),
            line("ONION YELLOW 50LB", 1, 3499, 0.95),
        ],
    )
    s = score(TRUTH, predicted)
    assert all(s.header.values())
    assert s.matched == 2
    assert all(all(oks) for oks in s.line_fields.values())


def test_misread_missed_and_invented_lines_are_counted() -> None:
    predicted = Extraction(
        supplier_name="Restaurant Depot",
        receipt_date=None,  # couldn't read the date
        total_cents=8238,  # misread total
        lines=[
            line("ONION YELLOW 50LB", 1, 3489, 0.97),  # confident but wrong total
            line("BAG FEE", 1, 10, 0.5),  # not on the truth: an extra line
        ],  # GHEE missed entirely
    )
    s = score(TRUTH, predicted)
    assert s.header == {"supplier_name": True, "receipt_date": False, "total_cents": False}
    assert (s.matched, s.truth_lines, s.predicted_lines) == (1, 2, 2)
    assert s.line_fields["line_total_cents"] == [False]
    assert s.calibration == [(0.97, False)]  # high confidence + wrong = miscalibration


def test_calibration_table_shows_threshold_tradeoff() -> None:
    points = [(0.95, True), (0.9, True), (0.85, False), (0.6, True), (0.4, False)]
    rows = {r["threshold"]: r for r in calibration_table(points)}
    assert rows[0.9] == {"threshold": 0.9, "auto_accepted_pct": 40.0, "error_rate_pct": 0.0}
    assert rows[0.8] == {"threshold": 0.8, "auto_accepted_pct": 60.0, "error_rate_pct": 33.3}


def test_cost_and_summary() -> None:
    assert cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == Decimal("0.60")
    perfect = Extraction(
        supplier_name="Restaurant Depot",
        receipt_date="2026-10-20",
        total_cents=8248,
        lines=[line("ONION YELLOW 50LB", 1, 3499, 0.9), line("GHEE 1.6KG", 3, 4749, 0.9)],
    )
    run = {
        "score": score(TRUTH, perfect),
        "latency_s": 2.0,
        "input_tokens": 2000,
        "output_tokens": 500,
        "failed": False,
    }
    report = summarize("claude-haiku-5-5", [run])
    assert report["header_accuracy_pct"]["total_cents"] == 100.0
    assert (report["line_recall_pct"], report["line_precision_pct"]) == (100.0, 100.0)
    assert report["cost_per_receipt_usd"] == "0.00045"  # (2000*0.10 + 500*0.50) / 1e6
