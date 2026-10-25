"""Adapter for reading a receipt photo with Claude vision. The only module that talks to the
Claude API: tests replace `extract`, so CI never calls (or pays for) the real model."""

import base64
import logging
from dataclasses import dataclass
from typing import Literal, cast

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel, Field

from app.observability import LLM_TOKENS

log = logging.getLogger(__name__)

# Bump when the prompt or schema changes: cached results and eval runs are keyed by it.
PROMPT_VERSION = "v1"
ImageType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]

PROMPT = """You are reading a supplier receipt or invoice from a restaurant's food supplier.
Extract the supplier, the date, the grand total, and every purchased line item.

Rules:
- Money is in integer cents (e.g. $12.50 -> 1250). Never guess a number you cannot read.
- quantity and unit are exactly as printed (e.g. 2 "case", 50 "lb", 1 "each").
- confidence is your probability (0 to 1) that the line's description, quantity and
  line total are all read correctly. Use low values for blurry, cut-off, handwritten
  or ambiguous lines; the owner reviews the lowest-confidence lines first.
- Skip tax, deposit, discount and subtotal lines; they are not purchased items.
- If a field is not on the receipt, return null."""


class ExtractedLine(BaseModel):
    description: str
    quantity: float
    unit: str
    unit_price_cents: int | None
    line_total_cents: int
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    supplier_name: str | None
    receipt_date: str | None = Field(description="ISO date YYYY-MM-DD")
    total_cents: int | None
    lines: list[ExtractedLine]


@dataclass(frozen=True)
class Result:
    extraction: Extraction
    model: str
    input_tokens: int
    output_tokens: int


class Unreadable(Exception):
    """Permanent: retrying the same image won't help (refusal, or output cut off)."""


async def extract(image: bytes, media_type: str, model: str) -> Result:
    """Raises Unreadable for permanent failures. Transient API errors (429, 5xx, network)
    propagate so the job queue retries them with backoff."""
    client = anthropic.AsyncAnthropic()  # credentials from ANTHROPIC_API_KEY
    message: MessageParam = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": cast(ImageType, media_type),
                    "data": base64.standard_b64encode(image).decode(),
                },
            },
            {"type": "text", "text": PROMPT},
        ],
    }
    response = await client.messages.parse(
        model=model,
        max_tokens=16000,
        messages=[message],
        output_format=Extraction,
    )
    usage = response.usage
    LLM_TOKENS.labels(model, "input").inc(usage.input_tokens)
    LLM_TOKENS.labels(model, "output").inc(usage.output_tokens)
    log.info(
        "receipt extraction model=%s input_tokens=%d output_tokens=%d stop=%s",
        model,
        usage.input_tokens,
        usage.output_tokens,
        response.stop_reason,
    )
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise Unreadable(f"model stopped with {response.stop_reason}")
    return Result(response.parsed_output, model, usage.input_tokens, usage.output_tokens)
