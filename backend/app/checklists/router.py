import uuid
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app import crud
from app.api import Limit, Page, etag, if_match
from app.auth.service import TenantSession
from app.checklists import service
from app.checklists.models import Template

router = APIRouter(prefix="/v1/checklists", tags=["checklists"])
IfMatch = Annotated[int, Depends(if_match)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Weekday = Annotated[int, Field(ge=0, le=6)]  # 0 = Monday
DueMinutes = Annotated[int, Field(ge=0, le=2880, description="Minutes after local midnight")]


class Item(BaseModel):
    # Kept stable across edits so check-offs keep pointing at the same item.
    id: UUID = Field(default_factory=uuid.uuid4)
    label: Label


class TemplateCreate(BaseModel):
    id: UUID | None = None
    name: Label
    days_of_week: Annotated[set[Weekday], Field(min_length=1)]
    due_minutes: DueMinutes
    items: Annotated[list[Item], Field(min_length=1, max_length=100)]


class TemplateUpdate(BaseModel):
    name: Label | None = None
    days_of_week: Annotated[set[Weekday], Field(min_length=1)] | None = None
    due_minutes: DueMinutes | None = None
    items: Annotated[list[Item], Field(min_length=1, max_length=100)] | None = None
    active: bool | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    days_of_week: list[int]
    due_minutes: int
    items: list[Item]
    active: bool
    version: int


class RunItem(Item):
    checked: bool


class RunOut(BaseModel):
    id: UUID
    template_id: UUID
    name: str
    business_date: date
    due_at: datetime
    completed_at: datetime | None
    items: list[RunItem]
    done: int
    total: int


class Today(BaseModel):
    date: date
    runs: list[RunOut]


class CheckIn(BaseModel):
    id: UUID = Field(description="Client-generated op id (UUIDv7): makes sync retries no-ops")
    item_id: UUID
    checked: bool = True
    checked_at: AwareDatetime = Field(description="When it happened on the device")


class ChecksIn(BaseModel):
    checks: Annotated[list[CheckIn], Field(max_length=500)]


def _values(body: TemplateCreate | TemplateUpdate, exclude_unset: bool) -> dict[str, Any]:
    values = body.model_dump(mode="json", exclude_unset=exclude_unset, exclude_none=True)
    if "days_of_week" in values:
        values["days_of_week"] = sorted(values["days_of_week"])
    return values


@router.post("/templates", status_code=201, response_model=TemplateOut)
async def create_template(body: TemplateCreate, session: TenantSession, response: Response) -> Any:
    row = await crud.create(session, Template, _values(body, exclude_unset=False))
    await service.ensure_schedule(session, await service.local_today(session))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/templates", response_model=Page[TemplateOut])
async def list_templates(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, Template, cursor, limit)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    """Changes apply from the next run; today's run keeps the items it started with."""
    values = _values(body, exclude_unset=True)
    row = await crud.update_versioned(session, Template, template_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/today", response_model=Today)
async def today(session: TenantSession, day: date | None = None) -> Any:
    """Runs for a business day (default: today, restaurant time). Creates them if the daily
    job hasn't yet, and re-seeds the daily job chain if it ever broke."""
    business_day = day or await service.local_today(session)
    await service.materialize(session, business_day)
    await service.ensure_schedule(session, await service.local_today(session))
    return {"date": business_day, "runs": await service.runs_for(session, business_day)}


@router.post("/runs/{run_id}/checks", response_model=RunOut)
async def record_checks(run_id: UUID, body: ChecksIn, session: TenantSession) -> Any:
    checks = [c.model_dump() for c in body.checks]
    return await service.record_checks(session, run_id, checks)
