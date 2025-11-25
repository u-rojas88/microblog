import os
from functools import lru_cache
from redis import Redis
from redis.connection import ConnectionPool


@lru_cache(maxsize=1)
def get_connection_pool() -> ConnectionPool:
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    return ConnectionPool.from_url(redis_url, decode_responses=True)


def get_redis() -> Redis:
    return Redis(connection_pool=get_connection_pool())


