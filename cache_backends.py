import asyncio
from typing import Any, Optional
import redis.asyncio as redis
import pickle
import time
from collections import OrderedDict

class BaseCacheBackend:
    async def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError
        
    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        raise NotImplementedError
        
    async def delete(self, key: str) -> None:
        raise NotImplementedError
        
    async def exists(self, key: str) -> bool:
        raise NotImplementedError

class MemoryCacheBackend(BaseCacheBackend):
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._cache = OrderedDict()
        self.max_size = max_size
        self.default_ttl = default_ttl
        
    async def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
            
        data, expiry = self._cache[key]
        if time.time() > expiry:
            await self.delete(key)
            return None
            
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return data
        
    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        if ttl is None:
            ttl = self.default_ttl
            
        expiry = time.time() + ttl
        
        # Remove if exists to update position
        if key in self._cache:
            del self._cache[key]
            
        # Check size and evict if needed (LRU)
        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
            
        self._cache[key] = (value, expiry)
        
    async def delete(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
            
    async def exists(self, key: str) -> bool:
        if key not in self._cache:
            return False
            
        _, expiry = self._cache[key]
        if time.time() > expiry:
            await self.delete(key)
            return False
        return True

class RedisCacheBackend(BaseCacheBackend):
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
    async def _get_connection(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url, encoding="utf-8")
        return self._redis
        
    async def get(self, key: str) -> Optional[Any]:
        r = await self._get_connection()
        data = await r.get(key)
        if data:
            return pickle.loads(data)
        return None
        
    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        r = await self._get_connection()
        data = pickle.dumps(value)
        await r.setex(key, ttl, data)
        
    async def delete(self, key: str) -> None:
        r = await self._get_connection()
        await r.delete(key)
        
    async def exists(self, key: str) -> bool:
        r = await self._get_connection()
        return await r.exists(key) == 1

class CacheManager:
    def __init__(self, backend: str = "memory", **kwargs):
        self.backend_type = backend
        if backend == "memory":
            # Only pass relevant kwargs to MemoryCacheBackend
            memory_kwargs = {
                'max_size': kwargs.get('max_size', 1000),
                'default_ttl': kwargs.get('default_ttl', 300)
            }
            self.backend = MemoryCacheBackend(**memory_kwargs)
        elif backend == "redis":
            redis_url = kwargs.get('redis_url', 'redis://localhost:6379')
            self.backend = RedisCacheBackend(redis_url)
        else:
            raise ValueError(f"Unsupported cache backend: {backend}")
            
    async def get(self, key: str) -> Optional[Any]:
        return await self.backend.get(key)
        
    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        await self.backend.set(key, value, ttl)
        
    async def delete(self, key: str) -> None:
        await self.backend.delete(key)
        
    async def exists(self, key: str) -> bool:
        return await self.backend.exists(key)