from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app import crud
from app.api import Limit, Page, etag, if_match
from app.auth.service import TenantSession
from app.inventory.models import Ingredient, IngredientPrice, Supplier
from app.inventory.schemas import (
    IngredientCreate,
    IngredientOut,
    IngredientUpdate,
    PriceCreate,
    PriceOut,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
)

router = APIRouter(prefix="/v1", tags=["inventory"])
IfMatch = Annotated[int, Depends(if_match)]


@router.post("/suppliers", status_code=201, response_model=SupplierOut)
async def create_supplier(body: SupplierCreate, session: TenantSession, response: Response) -> Any:
    row = await crud.create(session, Supplier, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/suppliers", response_model=Page[SupplierOut])
async def list_suppliers(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, Supplier, cursor, limit)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
async def get_supplier(supplier_id: UUID, session: TenantSession, response: Response) -> Any:
    row = await crud.get_or_404(session, Supplier, supplier_id)
    response.headers["ETag"] = etag(row.version)
    return row


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: UUID,
    body: SupplierUpdate,
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    values = body.model_dump(exclude_unset=True)
    row = await crud.update_versioned(session, Supplier, supplier_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.post("/ingredients", status_code=201, response_model=IngredientOut)
async def create_ingredient(
    body: IngredientCreate, session: TenantSession, response: Response
) -> Any:
    row = await crud.create(session, Ingredient, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/ingredients", response_model=Page[IngredientOut])
async def list_ingredients(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, Ingredient, cursor, limit)


@router.get("/ingredients/{ingredient_id}", response_model=IngredientOut)
async def get_ingredient(ingredient_id: UUID, session: TenantSession, response: Response) -> Any:
    row = await crud.get_or_404(session, Ingredient, ingredient_id)
    response.headers["ETag"] = etag(row.version)
    return row


@router.patch("/ingredients/{ingredient_id}", response_model=IngredientOut)
async def update_ingredient(
    ingredient_id: UUID,
    body: IngredientUpdate,
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    values = body.model_dump(exclude_unset=True)
    row = await crud.update_versioned(session, Ingredient, ingredient_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.post("/ingredients/{ingredient_id}/prices", status_code=201, response_model=PriceOut)
async def add_price(ingredient_id: UUID, body: PriceCreate, session: TenantSession) -> Any:
    await crud.get_or_404(session, Ingredient, ingredient_id)
    values = {**body.model_dump(exclude_none=True), "ingredient_id": ingredient_id}
    return await crud.create(session, IngredientPrice, values)


@router.get("/ingredients/{ingredient_id}/prices", response_model=Page[PriceOut])
async def list_prices(
    ingredient_id: UUID, session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    await crud.get_or_404(session, Ingredient, ingredient_id)
    where = IngredientPrice.ingredient_id == ingredient_id
    return await crud.page(session, IngredientPrice, cursor, limit, where)
