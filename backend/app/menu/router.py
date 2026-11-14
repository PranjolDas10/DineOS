from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app import crud
from app.api import Limit, Page, etag, if_match
from app.auth.service import TenantSession
from app.menu import service
from app.menu.models import MenuItem, Recipe
from app.menu.schemas import (
    DishCost,
    FoodCostReport,
    LineIn,
    LineOut,
    Lines,
    MarginWatch,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuMatrix,
    RecipeCostOut,
    RecipeCreate,
    RecipeOut,
    RecipeUpdate,
)
from app.orders import service as orders

router = APIRouter(prefix="/v1", tags=["menu"])
IfMatch = Annotated[int, Depends(if_match)]


@router.post("/recipes", status_code=201, response_model=RecipeOut)
async def create_recipe(body: RecipeCreate, session: TenantSession, response: Response) -> Any:
    row = await crud.create(session, Recipe, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/recipes", response_model=Page[RecipeOut])
async def list_recipes(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, Recipe, cursor, limit)


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
async def get_recipe(recipe_id: UUID, session: TenantSession, response: Response) -> Any:
    row = await crud.get_or_404(session, Recipe, recipe_id)
    response.headers["ETag"] = etag(row.version)
    return row


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
async def update_recipe(
    recipe_id: UUID,
    body: RecipeUpdate,
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    values = body.model_dump(exclude_unset=True)
    row = await crud.update_versioned(session, Recipe, recipe_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


# Lines share the recipe's ETag: they are part of the recipe, edited as one unit.
@router.get("/recipes/{recipe_id}/lines", response_model=Lines[LineOut])
async def get_lines(recipe_id: UUID, session: TenantSession, response: Response) -> Any:
    recipe, lines = await service.get_lines(session, recipe_id)
    response.headers["ETag"] = etag(recipe.version)
    return {"lines": lines}


@router.put("/recipes/{recipe_id}/lines", response_model=Lines[LineOut])
async def replace_lines(
    recipe_id: UUID,
    body: Lines[LineIn],
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    lines = [line.model_dump() for line in body.lines]
    recipe, rows = await service.replace_lines(session, recipe_id, version, lines)
    response.headers["ETag"] = etag(recipe.version)
    return {"lines": rows}


@router.post("/menu-items", status_code=201, response_model=MenuItemOut)
async def create_menu_item(body: MenuItemCreate, session: TenantSession, response: Response) -> Any:
    row = await crud.create(session, MenuItem, body.model_dump(exclude_none=True))
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/menu-items", response_model=Page[MenuItemOut])
async def list_menu_items(
    session: TenantSession, cursor: UUID | None = None, limit: Limit = 50
) -> Any:
    return await crud.page(session, MenuItem, cursor, limit)


@router.get("/menu-items/{item_id}", response_model=MenuItemOut)
async def get_menu_item(item_id: UUID, session: TenantSession, response: Response) -> Any:
    row = await crud.get_or_404(session, MenuItem, item_id)
    response.headers["ETag"] = etag(row.version)
    return row


@router.patch("/menu-items/{item_id}", response_model=MenuItemOut)
async def update_menu_item(
    item_id: UUID,
    body: MenuItemUpdate,
    version: IfMatch,
    session: TenantSession,
    response: Response,
) -> Any:
    values = body.model_dump(exclude_unset=True)
    row = await crud.update_versioned(session, MenuItem, item_id, version, values)
    response.headers["ETag"] = etag(row.version)
    return row


@router.get("/recipes/{recipe_id}/cost", response_model=RecipeCostOut)
async def get_recipe_cost(recipe_id: UUID, session: TenantSession) -> Any:
    return await service.recipe_cost(session, recipe_id)


@router.get("/menu-items/{item_id}/cost", response_model=DishCost)
async def get_dish_cost(item_id: UUID, session: TenantSession) -> Any:
    return await service.dish_cost(session, item_id)


@router.get("/reports/food-cost", response_model=FoodCostReport)
async def food_cost_report(session: TenantSession) -> Any:
    return {"items": await service.food_cost_report(session)}


@router.get("/reports/margin-watch", response_model=MarginWatch)
async def margin_watch(
    session: TenantSession, days: Annotated[int, Query(ge=1, le=90)] = 28
) -> Any:
    """Composed here, not in menu.service: sales volume belongs to orders, and orders.service
    already imports menu.service, so the service can't import it back."""
    since = datetime.now(UTC) - timedelta(days=days)
    sold = await orders.units_sold(session, since)
    return await service.margin_watch(session, since, days, sold)


@router.get("/reports/menu-matrix", response_model=MenuMatrix)
async def menu_matrix(session: TenantSession, days: Annotated[int, Query(ge=1, le=90)] = 28) -> Any:
    sold = await orders.units_sold(session, datetime.now(UTC) - timedelta(days=days))
    return await service.menu_matrix(session, days, sold)
