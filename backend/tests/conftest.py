from collections.abc import AsyncIterator

import pytest

from app.db import engine


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def _dispose_pool() -> AsyncIterator[None]:
    """Each test runs on a new event loop; pooled asyncpg connections are bound to the old one."""
    yield
    await engine.dispose()
