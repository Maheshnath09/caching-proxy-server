import os
from typing import Optional

class Settings:
    def __init__(self):
        # Server settings
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.cache_ttl = int(os.getenv("CACHE_TTL", "300"))
        
        # Cache backend (memory, redis)
        self.cache_backend = os.getenv("CACHE_BACKEND", "memory")
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
        # Security
        self.max_cache_size = int(os.getenv("MAX_CACHE_SIZE", "1000"))
        self.allowed_domains = ["*"]

settings = Settings()