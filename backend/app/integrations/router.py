from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.auth.service import TenantSession
from app.integrations import service

router = APIRouter(tags=["integrations"])


class IntegrationIn(BaseModel):
    provider: Literal["uber_eats"]
    # The platform's store id (Uber: the store UUID the webhooks carry as meta.user_id).
    external_store_id: str = Field(min_length=1, max_length=200)
    # Accept new orders automatically once they are recorded (Uber cancels after 11.5 min).
    auto_accept: bool = True


class IntegrationOut(BaseModel):
    id: UUID
    provider: str
    external_store_id: str
    auto_accept: bool
    created_at: datetime


class IntegrationList(BaseModel):
    items: list[IntegrationOut]


@router.get("/v1/integrations", response_model=IntegrationList)
async def list_integrations(session: TenantSession) -> Any:
    return {"items": await service.list_integrations(session)}


@router.post("/v1/integrations", response_model=IntegrationOut, status_code=201)
async def connect_integration(body: IntegrationIn, session: TenantSession) -> Any:
    return await service.connect(session, body.provider, body.external_store_id, body.auto_accept)


@router.delete("/v1/integrations/{integration_id}", status_code=204)
async def disconnect_integration(integration_id: UUID, session: TenantSession) -> Response:
    await service.disconnect(session, integration_id)
    return Response(status_code=204)


@router.post("/v1/webhooks/uber-eats", status_code=200, include_in_schema=False)
async def uber_eats_webhook(request: Request) -> Response:
    """Called by Uber, not by our clients: authenticated by signature, not a bearer token."""
    await service.receive_uber_eats(await request.body(), request.headers.get("x-uber-signature"))
    return Response(status_code=200)
