from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime

from app import crud
from app.api import Limit, Page, etag, if_match
from app.auth.service import TenantSession
from app.scheduling import service
from app.scheduling.models import Shift, Staff
from app.scheduling.schemas import (
    LaborReport,
    ShiftCreate,
    ShiftList,
    ShiftOut,
    ShiftUpdate,
    StaffCreate,
    StaffOut,
    StaffUpdate,
)

router = APIRouter(prefix="/v1", tags=["scheduling"])
IfMatch = Annotated[int, Depends(if_match)]


@router.post("/staff", status_code=201, response_model=StaffOut)
async def create_staff(body: StaffCreate, session: TenantSession, response: Response) -> Any:
    row = await crud.create(session, Staff, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/staff", response_model=Page[StaffOut])
async def list_staff(session: TenantSession, cursor: UUID | None = None, limit: Limit = 50) -> Any:
    return await crud.page(session, Staff, cursor, limit)


@router.get("/staff/{staff_id}", response_model=StaffOut)
async def get_staff(staff_id: UUID, session: TenantSession, response: Response) -> Any:
    row = await crud.get_or_404(session, Staff, staff_id)
    response.headers["ETag"] = etag(row.version)
    return row


@router.patch("/staff/{staff_id}", response_model=StaffOut)
async def update_staff(
    staff_id: UUID, body: StaffUpdate, version: IfMatch, session: TenantSession, response: Response
) -> Any:
    values = body.model_dump(exclude_unset=True)
    row = await crud.update_versioned(session, Staff, staff_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.post("/shifts", status_code=201, response_model=ShiftOut)
async def create_shift(body: ShiftCreate, session: TenantSession, response: Response) -> Any:
    """409 if this person already has an overlapping shift (enforced by the database)."""
    row = await service.create_shift(session, body)
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/shifts", response_model=ShiftList)
async def list_shifts(
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
    session: TenantSession,
) -> Any:
    return {"items": await service.list_shifts(session, start, end)}


@router.patch("/shifts/{shift_id}", response_model=ShiftOut)
async def move_shift(
    shift_id: UUID, body: ShiftUpdate, version: IfMatch, session: TenantSession, response: Response
) -> Any:
    row = await service.move_shift(session, shift_id, version, body)
    response.headers["ETag"] = etag(row.version)
    return row


@router.delete("/shifts/{shift_id}", status_code=204)
async def delete_shift(shift_id: UUID, version: IfMatch, session: TenantSession) -> Response:
    await crud.delete_versioned(session, Shift, shift_id, version)
    return Response(status_code=204)


@router.get("/reports/labor-cost", response_model=LaborReport)
async def labor_cost(
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
    session: TenantSession,
) -> Any:
    return await service.labor_report(session, first, last)
