"""
API Gateway for Microblog

An API gateway acts as a single entry point for all client requests to the microservices.
It routes requests to the appropriate backend service (users_service or timelines_service)
and forwards responses back to the client.

Benefits:
- Single entry point for clients (simplifies client code)
- Centralized request routing
- Can add cross-cutting concerns like rate limiting, logging, monitoring
- Can aggregate responses from multiple services
- Hides internal service structure from clients
"""

import os
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import Response
import httpx
from registry_service.discovery import get_service_url


app = FastAPI(title="Microblog API Gateway")

# HTTP client with timeout
HTTP_TIMEOUT = 30.0


async def proxy_request(
    request: Request,
    service_url: str,
    path: str,
    method: str = None,
) -> Response:
    """
    Proxy a request to a backend service.
    
    Args:
        request: The incoming FastAPI request
        service_url: Base URL of the backend service
        path: Path to append to service_url (should start with /)
        method: HTTP method (defaults to request.method)
    
    Returns:
        Response from the backend service
    """
    method = method or request.method
    url = f"{service_url}{path}"
    
    # Get request body if present
    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
    
    # Forward all headers (especially Authorization)
    headers = dict(request.headers)
    # Remove host header to avoid conflicts
    headers.pop("host", None)
    # Remove connection header
    headers.pop("connection", None)
    
    # Forward query parameters
    params = dict(request.query_params)
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                content=body,
            )
            
            # Return response with same status code and headers
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Backend service timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot connect to backend service"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error: {str(e)}"
        )


# Route: Users Service endpoints
@app.api_route("/users/{username}/likes", methods=["GET"])
async def likes_user_likes_proxy(request: Request, username: str):
    """Proxy the specific user likes endpoint to likes service (overrides generic /users/* rule)."""
    likes_service_url = await get_service_url("likes")
    if not likes_service_url:
        raise HTTPException(status_code=502, detail="Likes service not available")
    full_path = f"/users/{username}/likes"
    return await proxy_request(request, likes_service_url, full_path)

@app.api_route("/register", methods=["POST"])
@app.api_route("/login", methods=["POST"])
async def users_service_auth_proxy(request: Request):
    """Proxy authentication requests to the users service."""
    users_service_url = await get_service_url("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    return await proxy_request(request, users_service_url, request.url.path)


@app.api_route("/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def users_service_proxy(request: Request, path: str):
    """Proxy requests to the users service."""
    users_service_url = await get_service_url("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    # Reconstruct the full path
    full_path = f"/users/{path}"
    return await proxy_request(request, users_service_url, full_path)


# Route: Timelines Service endpoints
@app.api_route("/posts", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def timelines_service_root_proxy(request: Request):
    """Proxy requests to /posts endpoint."""
    timelines_service_url = await get_service_url("timelines")
    if not timelines_service_url:
        raise HTTPException(status_code=502, detail="Timelines service not available")
    return await proxy_request(request, timelines_service_url, "/posts")


@app.api_route("/posts/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def timelines_service_proxy(request: Request, path: str):
    """Proxy requests to the timelines service."""
    timelines_service_url = await get_service_url("timelines")
    if not timelines_service_url:
        raise HTTPException(status_code=502, detail="Timelines service not available")
    full_path = f"/posts/{path}"
    return await proxy_request(request, timelines_service_url, full_path)


# Route: Likes Service endpoints
@app.api_route("/likes", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def likes_service_root_proxy(request: Request):
    """Proxy requests to /likes endpoint."""
    likes_service_url = await get_service_url("likes")
    if not likes_service_url:
        raise HTTPException(status_code=502, detail="Likes service not available")
    return await proxy_request(request, likes_service_url, "/likes")


@app.api_route("/likes/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def likes_service_proxy(request: Request, path: str):
    """Proxy requests to the likes service."""
    likes_service_url = await get_service_url("likes")
    if not likes_service_url:
        raise HTTPException(status_code=502, detail="Likes service not available")
    full_path = f"/likes/{path}"
    return await proxy_request(request, likes_service_url, full_path)


# Route: Polls Service endpoints
@app.api_route("/polls", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def polls_service_root_proxy(request: Request):
    """Proxy requests to /polls endpoint."""
    polls_service_url = await get_service_url("polls")
    if not polls_service_url:
        raise HTTPException(status_code=502, detail="Polls service not available")
    return await proxy_request(request, polls_service_url, "/polls")


@app.api_route("/polls/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def polls_service_proxy(request: Request, path: str):
    """Proxy requests to the polls service."""
    polls_service_url = await get_service_url("polls")
    if not polls_service_url:
        raise HTTPException(status_code=502, detail="Polls service not available")
    full_path = f"/polls/{path}"
    return await proxy_request(request, polls_service_url, full_path)


@app.get("/health")
async def health_check():
    """Health check endpoint for the gateway."""
    return {"status": "ok", "service": "gateway"}


@app.get("/")
async def root():
    """Root endpoint with API information."""
    # Get current service URLs from registry
    users_url = await get_service_url("users")
    timelines_url = await get_service_url("timelines")
    likes_url = await get_service_url("likes")
    polls_url = await get_service_url("polls")
    
    return {
        "service": "Microblog API Gateway",
        "version": "1.0.0",
        "endpoints": {
            "users": users_url or "not available",
            "timelines": timelines_url or "not available",
            "likes": likes_url or "not available",
            "polls": polls_url or "not available",
        },
        "docs": "/docs",
    }

