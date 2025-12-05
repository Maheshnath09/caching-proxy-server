from pydantic import BaseModel
from typing import Dict, Any, Optional

class ProxyRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    params: Optional[Dict[str, Any]] = None

class CacheInfo(BaseModel):
    key: str
    hits: int = 0
    size: Optional[int] = None
    created_at: float
    expires_at: float

class ProxyResponse(BaseModel):
    status_code: int
    content: bytes
    headers: Dict[str, str]
    from_cache: bool = False
    cache_key: Optional[str] = None