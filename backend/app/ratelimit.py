"""Token-bucket rate limits in Redis, shared by every API replica.

A bucket holds up to `capacity` tokens and refills at `per_second`. Each request takes one;
an empty bucket means 429 with Retry-After. The whole read-refill-take step runs as one Lua
script, so concurrent requests on different replicas can't both take the last token, and it
uses Redis's clock (TIME), so replicas with skewed clocks agree.

If Redis is down, requests are allowed (fail open) and a warning is logged: a cache outage
shouldn't take the restaurant's app down. Redis only ever holds data that can be lost.
"""

import logging
from dataclasses import dataclass

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.api import Problem
from app.config import settings

log = logging.getLogger(__name__)
client = redis.from_url(settings.redis_url)

_BUCKET = client.register_script("""
local capacity, rate = tonumber(ARGV[1]), tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1e6
local b = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens, ts = tonumber(b[1]) or capacity, tonumber(b[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = tokens >= 1
if allowed then tokens = tokens - 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000))
if allowed then return 0 end
return math.ceil((1 - tokens) / rate * 1000)
""")


@dataclass(frozen=True)
class Limit:
    name: str
    capacity: int  # burst size
    per_second: float  # sustained rate


# Generous per restaurant: stops a runaway client or loop, never a busy dinner rush.
TENANT = Limit("tenant", capacity=200, per_second=20)
# Password guessing: 5 tries per account, then one a minute; an IP gets a little more room.
LOGIN_ACCOUNT = Limit("login-account", capacity=5, per_second=1 / 60)
LOGIN_IP = Limit("login-ip", capacity=20, per_second=1 / 6)


async def check(limit: Limit, key: str) -> None:
    """Take one token from this key's bucket, or raise 429 with Retry-After."""
    try:
        wait_ms = int(
            await _BUCKET(keys=[f"rl:{limit.name}:{key}"], args=[limit.capacity, limit.per_second])
        )
    except RedisError:
        log.warning("rate limiter unavailable; allowing request (%s)", limit.name, exc_info=True)
        return
    if wait_ms:
        seconds = max(1, -(-wait_ms // 1000))  # round up: never tell a client to retry too early
        raise Problem(429, "Too many requests. Try again shortly.", {"Retry-After": str(seconds)})
