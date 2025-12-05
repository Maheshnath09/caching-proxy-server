from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import Response
import httpx
import hashlib
import json
import time
from typing import Optional, Dict, Any
import gzip

from config import settings
from cache_backends import CacheManager
from models import ProxyRequest, ProxyResponse, CacheInfo

# Initialize cache based on backend type
if settings.cache_backend == "memory":
    cache_manager = CacheManager(
        backend="memory",
        max_size=settings.max_cache_size,
        default_ttl=settings.cache_ttl
    )
elif settings.cache_backend == "redis":
    cache_manager = CacheManager(
        backend="redis",
        redis_url=settings.redis_url
    )
else:
    raise ValueError(f"Unsupported cache backend: {settings.cache_backend}")

# Statistics
cache_stats = {
    "hits": 0,
    "misses": 0,
    "total_requests": 0
}

app = FastAPI(
    title="Caching Proxy Server",
    description="A smart caching proxy for HTTP requests",
    version="1.0.0"
)

def generate_cache_key(request: ProxyRequest) -> str:
    """Generate unique cache key for request"""
    key_data = {
        "url": request.url,
        "method": request.method,
        "params": request.params or {},
        "body": request.body
    }
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_string.encode()).hexdigest()

def is_cacheable_response(status_code: int, headers: Dict[str, str]) -> bool:
    """Check if response should be cached"""
    if status_code not in [200, 301, 302]:
        return False
        
    # Don't cache responses with certain headers
    cache_control = headers.get("cache-control", "").lower()
    if "no-store" in cache_control or "no-cache" in cache_control:
        return False
        
    return True

async def make_http_request(request: ProxyRequest) -> ProxyResponse:
    """Make actual HTTP request to target"""
    async with httpx.AsyncClient() as client:
        # Prepare request parameters
        kwargs = {
            "method": request.method,
            "url": request.url,
            "headers": request.headers or {},
            "params": request.params or {},
            "follow_redirects": True
        }
        
        if request.body and request.method in ["POST", "PUT", "PATCH"]:
            if isinstance(request.body, (dict, list)):
                kwargs["json"] = request.body
            else:
                kwargs["data"] = request.body
            
        # Make request
        response = await client.request(**kwargs)
        
        return ProxyResponse(
            status_code=response.status_code,
            content=response.content,
            headers=dict(response.headers),
            from_cache=False
        )

async def process_proxy_request(request: ProxyRequest, ttl: Optional[int] = None) -> ProxyResponse:
    """Process proxy request with caching"""
    cache_stats["total_requests"] += 1
    
    # Generate cache key
    cache_key = generate_cache_key(request)
    
    # Check cache
    cached_response = await cache_manager.get(cache_key)
    if cached_response:
        cache_stats["hits"] += 1
        cached_response.from_cache = True
        cached_response.cache_key = cache_key
        return cached_response
        
    cache_stats["misses"] += 1
    
    # Make actual request
    response = await make_http_request(request)
    response.cache_key = cache_key
    
    # Cache if cacheable
    if is_cacheable_response(response.status_code, response.headers):
        cache_ttl = ttl or settings.cache_ttl
        await cache_manager.set(cache_key, response, cache_ttl)
    
    return response

# Middleware for direct HTTP proxy
@app.middleware("http")
async def direct_proxy_middleware(request: Request, call_next):
    """Middleware to handle direct proxy requests"""
    
    # Only process paths starting with /http/
    if not request.url.path.startswith("/http/"):
        return await call_next(request)
    
    try:
        # Extract the target URL from the path
        path_parts = request.url.path.split("/http/", 1)
        if len(path_parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid proxy path")
        
        target_path = path_parts[1]
        full_url = f"https://{target_path}"
        
        # Add query parameters if any
        if request.url.query:
            full_url += f"?{request.url.query}"
        
        # Prepare headers - remove headers that shouldn't be forwarded
        headers = {}
        for key, value in request.headers.items():
            if key.lower() not in ['host', 'content-length', 'content-encoding', 'accept-encoding']:
                headers[key] = value
        
        # Add our own accept-encoding to control response format
        headers['accept-encoding'] = 'identity'  # Request uncompressed content
        
        # Prepare proxy request
        proxy_request_data = ProxyRequest(
            url=full_url,
            method=request.method,
            headers=headers
        )
        
        # Handle request body
        if request.method in ["POST", "PUT", "PATCH"]:
            body_bytes = await request.body()
            if body_bytes:
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        proxy_request_data.body = json.loads(body_bytes.decode())
                    except:
                        proxy_request_data.body = body_bytes.decode()
                else:
                    proxy_request_data.body = body_bytes.decode()
        
        # Process the proxy request
        response_data = await process_proxy_request(proxy_request_data)
        
        # Prepare response headers - remove encoding headers that might cause issues
        response_headers = {}
        for key, value in response_data.headers.items():
            if key.lower() not in ['content-encoding', 'transfer-encoding', 'content-length']:
                response_headers[key] = value
        
        # Return the response
        return Response(
            content=response_data.content,
            status_code=response_data.status_code,
            headers=response_headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in proxy middleware: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

# Regular endpoints
@app.post("/proxy")
async def proxy_request(request: ProxyRequest, ttl: Optional[int] = Query(None)):
    """Main proxy endpoint"""
    return await process_proxy_request(request, ttl)

@app.get("/cache/info/{cache_key}")
async def get_cache_info(cache_key: str):
    """Get information about cached item"""
    cached_item = await cache_manager.get(cache_key)
    if not cached_item:
        raise HTTPException(status_code=404, detail="Cache key not found")
        
    return {
        "key": cache_key,
        "exists": True,
        "status_code": cached_item.status_code,
        "from_cache": cached_item.from_cache
    }

@app.delete("/cache/{cache_key}")
async def delete_cache_item(cache_key: str):
    """Delete specific cache item"""
    await cache_manager.delete(cache_key)
    return {"message": f"Cache item {cache_key} deleted"}

@app.delete("/cache/clear")
async def clear_cache():
    """Clear all cache"""
    if settings.cache_backend == "memory":
        cache_manager.backend._cache.clear()
    return {"message": "Cache cleared"}

@app.get("/stats")
async def get_stats():
    """Get cache statistics"""
    total = cache_stats["total_requests"]
    hits = cache_stats["hits"]
    hit_rate = (hits / total * 100) if total > 0 else 0
    
    return {
        **cache_stats,
        "hit_rate": round(hit_rate, 2),
        "cache_backend": settings.cache_backend
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "cache_backend": settings.cache_backend,
        "timestamp": time.time()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )