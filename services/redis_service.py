import asyncio
from typing import Optional

import redis.asyncio as redis

import config
from utils.logger import logger


class RedisClientWrapper:
    def __init__(self):
        self.client = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize Redis connection with timeout and retry."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                try:
                    self.client = redis.Redis(
                        host=config.REDIS_HOST,
                        port=config.REDIS_PORT,
                        db=config.REDIS_DB,
                        decode_responses=True,
                        username=config.REDIS_USERNAME,
                        password=config.REDIS_PASSWORD,
                        socket_timeout=10,
                        socket_connect_timeout=10,
                        max_connections=config.MAX_REDIS_CONNECTIONS,
                        retry_on_timeout=True,
                        health_check_interval=30,
                        socket_keepalive=True,
                    )

                    # Test connection with PING
                    if await self.client.ping():
                        self._initialized = True
                        logger.info(
                            "Redis init: host=%s, port=%s, db=%s",
                            config.REDIS_HOST,
                            config.REDIS_PORT,
                            config.REDIS_DB
                        )
                        return
                    else:
                        raise Exception("Ping returned False")
                except Exception as e:
                    logger.error(
                        "Redis initialization attempt %d failed: %s",
                        attempt,
                        e
                    )
                    await asyncio.sleep(3)  # increased sleep duration

            raise Exception("Failed to initialize Redis client after "
                            "several attempts")

    async def ensure_connection(self):
        """Ensure Redis connection is established and functioning."""
        if not self._initialized:
            await self.initialize()
        else:
            try:
                await self.client.ping()
            except Exception as e:
                logger.error(
                    "Redis connection error: %s. Reinitializing connection.",
                    e
                )
                await self.close()
                await self.initialize()

    async def ping(self):
        """Check if Redis connection is alive."""
        try:
            await self.ensure_connection()
            return await self.client.ping()
        except Exception as e:
            logger.error(
                "Redis ping failed: %s",
                e
            )
            return False

    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        await self.ensure_connection()
        return await self.client.get(key)

    async def set(
        self, key: str, value: str,
        expire: Optional[int] = None,
        ex: Optional[int] = None
    ) -> bool:
        """Set value in Redis with optional expiration.

        Args:
            key: The key to set.
            value: The value to set.
            expire: Optional expiration time in seconds
                    (deprecated, use ex instead).
            ex: Optional expiration time in seconds.
        """
        await self.ensure_connection()
        # Use ex parameter if provided, otherwise fall back to expire
        expiration = ex if ex is not None else expire
        if expiration:
            return bool(await self.client.set(key, value, ex=expiration))
        return bool(await self.client.set(key, value))

    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        await self.ensure_connection()
        return bool(await self.client.delete(key))

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        await self.ensure_connection()
        return bool(await self.client.exists(key))

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time for key."""
        await self.ensure_connection()
        return bool(await self.client.expire(key, seconds))

    async def ttl(self, key: str) -> int:
        """Get time to live for key."""
        await self.ensure_connection()
        return await self.client.ttl(key)

    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self._initialized = False

    async def lpush(self, key: str, value: str):
        """Push value to the head of list."""
        await self.ensure_connection()
        return await self.client.lpush(key, value)

    async def rpop(self, key: str) -> str:
        """Pop value from the tail of list."""
        await self.ensure_connection()
        return await self.client.rpop(key)

    async def llen(self, key: str) -> int:
        """Get length of list."""
        await self.ensure_connection()
        return await self.client.llen(key)

    async def publish(self, channel: str, message: str):
        """Publish message to channel."""
        await self.ensure_connection()
        return await self.client.publish(channel, message)

    async def pipeline(self):
        """Get a Redis pipeline for batch operations."""
        await self.ensure_connection()
        pipe = self.client.pipeline()
        return pipe

    async def execute_pipeline(self, pipe):
        """Execute a Redis pipeline and return results."""
        try:
            return await pipe.execute()
        except Exception as e:
            logger.error(
                "Error executing Redis pipeline: %s",
                e
            )
            raise

    async def keys(self, pattern: str) -> list:
        """Get keys matching pattern."""
        await self.ensure_connection()
        return await self.client.keys(pattern)

    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment the value of a key by the specified amount.

        Args:
            key: The key to increment
            amount: The amount to increment by (default: 1)

        Returns:
            The new value after incrementing
        """
        await self.ensure_connection()
        return await self.client.incr(key, amount)

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        """Set the value and expiration of a key.

        Args:
            key: The key to set
            seconds: The expiration time in seconds
            value: The value to set

        Returns:
            True if successful, False otherwise
        """
        await self.ensure_connection()
        return bool(await self.client.setex(key, seconds, value))
