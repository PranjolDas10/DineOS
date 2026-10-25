"""HTTP conventions shared by every module: RFC 9457 errors, ETag/If-Match, cursor pages."""

from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

Limit = Annotated[int, Query(ge=1, le=200)]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: UUID | None


class Problem(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


def problem(status: int, detail: str, **extra: Any) -> JSONResponse:
    # type about:blank means "nothing beyond the HTTP status", so title is the status phrase.
    body = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status}
    return JSONResponse(
        {**body, "detail": detail, **extra},
        status_code=status,
        media_type="application/problem+json",
    )


def etag(version: int) -> str:
    return f'"{version}"'


def if_match(if_match: Annotated[str | None, Header()] = None) -> int:
    """Required on updates: a client that never read the row must not blindly overwrite it."""
    if if_match is None:
        raise Problem(428, "Send If-Match with the ETag from your last read.")
    try:
        return int(if_match.removeprefix("W/").strip('"'))
    except ValueError:
        raise Problem(412, "If-Match is not a valid ETag.") from None


# Postgres SQLSTATE -> HTTP. Constraints are the source of truth; the API just translates.
_INTEGRITY_STATUS = {"23505": (409, "A record with this value already exists.")}
# Specific constraints with a message the owner can act on. Checked before the SQLSTATE map.
_CONSTRAINT_STATUS = {
    "recipe_lines_no_cycle": (409, "A recipe can't use itself, directly or through sub-recipes."),
}


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(_: Request, exc: Problem) -> JSONResponse:
        return problem(exc.status, exc.detail)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return problem(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(422, "Request is invalid.", errors=jsonable_encoder(exc.errors()))

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # SQLAlchemy's asyncpg wrapper chains the driver error, which carries the constraint name.
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        sqlstate = getattr(exc.orig, "sqlstate", None)
        status, detail = (
            _CONSTRAINT_STATUS.get(constraint or "")
            or _INTEGRITY_STATUS.get(sqlstate or "")
            or (422, "Request violates a data constraint.")
        )
        return problem(status, detail)
