from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from app.api import Problem
from app.auth.service import TenantSession
from app.ledger import service

router = APIRouter(prefix="/v1", tags=["ledger"])
Channel = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=40)
]


class ChannelFee(BaseModel):
    channel: str
    commission_bps: int


class ChannelFeeIn(BaseModel):
    commission_bps: Annotated[int, Field(ge=0, le=10_000, description="30% = 3000")]


class ProfitRow(BaseModel):
    revenue_cents: int
    commission_cents: int
    food_cost_cents: int
    gross_profit_cents: int


class ChannelProfit(ProfitRow):
    channel: str
    labor_cents: int
    profit_cents: int


class DishProfit(ProfitRow):
    menu_item_id: UUID | None
    name: str


class DayProfit(ProfitRow):
    date: date
    labor_cents: int
    profit_cents: int


class ProfitReport(BaseModel):
    labor_cents: int
    sales_with_unknown_food_cost: int
    daily: list[DayProfit]
    channels: list[ChannelProfit]
    dishes: list[DishProfit]


@router.get("/channel-fees", response_model=list[ChannelFee])
async def list_fees(session: TenantSession) -> Any:
    rows = await session.execute(
        text("SELECT channel, commission_bps FROM channel_fees ORDER BY channel")
    )
    return [dict(r._mapping) for r in rows]


@router.put("/channel-fees/{channel}", response_model=ChannelFee)
async def set_fee(channel: Channel, body: ChannelFeeIn, session: TenantSession) -> Any:
    """Applies to orders posted from now on; past postings keep the fee they were posted with."""
    await session.execute(
        text(
            "INSERT INTO channel_fees (channel, commission_bps) VALUES (:c, :b)"
            " ON CONFLICT (tenant_id, channel)"
            " DO UPDATE SET commission_bps = excluded.commission_bps, updated_at = now()"
        ),
        {"c": channel, "b": body.commission_bps},
    )
    return {"channel": channel, "commission_bps": body.commission_bps}


@router.get("/reports/profit", response_model=ProfitReport)
async def profit(
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
    session: TenantSession,
) -> Any:
    if not timedelta(0) <= last - first <= timedelta(days=31):
        raise Problem(422, "to must be on or after from, at most 31 days later.")
    return await service.profit_report(session, first, last)
