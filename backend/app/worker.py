"""Background worker: python -m app.worker. Run more processes for more parallelism
(docker compose up --scale worker=3); SKIP LOCKED keeps them from colliding."""

import asyncio
import logging

from app import jobs

# Importing a module registers its @jobs.job handlers.
from app.checklists import service as _checklists  # noqa: F401
from app.receipts import service as _receipts  # noqa: F401

POLL_SECONDS = 1.0


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        if await jobs.run_once() is None:
            # ponytail: polling; LISTEN/NOTIFY if idle-to-start latency ever matters
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
