"""Background worker: python -m app.worker. Run more processes for more parallelism
(docker compose up --scale worker=3); SKIP LOCKED keeps them from colliding."""

import asyncio

from app import jobs

# Importing a module registers its @jobs.job handlers.
from app.checklists import service as _checklists  # noqa: F401
from app.config import settings
from app.observability import setup_logging, start_metrics_server
from app.orders import service as _orders  # noqa: F401
from app.receipts import service as _receipts  # noqa: F401

POLL_SECONDS = 1.0


async def main() -> None:
    setup_logging()
    start_metrics_server(settings.metrics_port)
    while True:
        if await jobs.run_once() is None:
            # ponytail: polling; LISTEN/NOTIFY if idle-to-start latency ever matters
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
