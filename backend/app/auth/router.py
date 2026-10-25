from typing import Annotated, Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, StringConstraints

from app.auth import service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    # Upper bound so a huge body can't make argon2 burn CPU (cheap DoS).
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class RefreshIn(BaseModel):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@router.post("/login", response_model=TokenPair)
async def login(body: LoginIn) -> Any:
    return await service.login(body.email, body.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn) -> Any:
    return await service.refresh(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn) -> Response:
    await service.logout(body.refresh_token)
    return Response(status_code=204)
