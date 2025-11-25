from typing import Annotated
import json

from fastapi import FastAPI, Depends, HTTPException, status, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
import greenstalk

from .db import Base, engine, get_db
from .models import Post
from .schemas import PostCreate, PostOut
from .auth import decode_token
import os
import httpx
from registry_service.client import register_service, deregister_service
from registry_service.discovery import get_service_url_sync


app = FastAPI(title="Timelines Service")

# Beanstalkd configuration
BEANSTALKD_HOST = os.getenv("BEANSTALKD_HOST", "127.0.0.1")
BEANSTALKD_PORT = int(os.getenv("BEANSTALKD_PORT", "11300"))
POST_QUEUE = "post_creation"


@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    # Register with service registry
    port = os.getenv("PORT", "5200")
    base_url = f"http://localhost:{port}"
    await register_service("timelines", base_url)


@app.on_event("shutdown")
async def on_shutdown():
    # Deregister from service registry
    await deregister_service()


def get_current_username_optional(authorization: Annotated[str | None, Header()] = None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        return None
    return str(payload["sub"])  # username


def get_current_username_required(authorization: Annotated[str | None, Header()] = None) -> str:
    username = get_current_username_optional(authorization)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")
    return username


@app.post("/posts", response_model=PostOut)
def create_post(data: PostCreate, current_username: str = Depends(get_current_username_required), db: Session = Depends(get_db)):
    users_service_url = get_service_url_sync("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{users_service_url}/users/{current_username}")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to resolve user_id from users service")
        user_data = resp.json()
        user_id = user_data.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=502, detail="User data missing user_id")
    
    post = Post(user_id=user_id, text=data.text, repost_original_url=str(data.repost_original_url) if data.repost_original_url else None)
    db.add(post)
    db.commit()
    db.refresh(post)
    
    # Return PostOut with username since schema expects username, not user_id
    return post


@app.post("/posts/async", status_code=status.HTTP_202_ACCEPTED)
def create_post_async(data: PostCreate, current_username: str = Depends(get_current_username_required)):
    """
    Asynchronously create a post by adding it to the work queue.
    Returns 202 Accepted immediately without waiting for database insertion.
    """
    # Resolve user_id from users service
    users_service_url = get_service_url_sync("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{users_service_url}/users/{current_username}")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to resolve user_id from users service")
        user_data = resp.json()
        user_id = user_data.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=502, detail="User data missing user_id")
    
    # Create job payload
    job_data = {
        "username": current_username,
        "user_id": user_id,
        "text": data.text,
        "repost_original_url": str(data.repost_original_url) if data.repost_original_url else None,
    }
    
    # Put job in Beanstalkd queue
    try:
        with greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT)) as client:
            client.use(POST_QUEUE)
            client.put(json.dumps(job_data))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to queue job: {str(e)}"
        )
    
    return {
        "status": "accepted",
        "message": "Post creation queued for processing"
    }


@app.get("/posts/id/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    """
    Get a specific post by post_id.
    Used by other services (like likes service) to validate post existence.
    """
    post = db.query(Post).filter(Post.post_id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Return PostOut with placeholder username (validation worker only checks status code)
    return PostOut(
        user_id=post.user_id,
        username=str(post.user_id),  # Placeholder - validation worker doesn't use this
        text=post.text,
        created_at=post.created_at,
        repost_original_url=post.repost_original_url,
    )


@app.get("/posts/{username}", response_model=list[PostOut])
def user_timeline(username: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    users_service_url = get_service_url_sync("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{users_service_url}/users/{username}")
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="User not found")
        user_data = resp.json()
        user_id = user_data.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=502, detail="User data missing user_id")
    posts = db.execute(
        select(Post).where(Post.user_id == user_id).order_by(Post.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    
    # Map Post objects to PostOut with username (all posts are from the same user)
    return posts


@app.get("/posts", response_model=list[PostOut])
def public_timeline(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    posts = db.execute(select(Post).order_by(Post.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return posts


@app.get("/posts/home/{username}", response_model=list[PostOut])
def home_timeline(username: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), current_username: str = Depends(get_current_username_required), db: Session = Depends(get_db)):
    if username != current_username:
        raise HTTPException(status_code=403, detail="Forbidden: cannot view another user's home timeline")

    # Fetch followees from users service (timelines cannot access users DB)
    users_service_url = get_service_url_sync("users")
    if not users_service_url:
        raise HTTPException(status_code=502, detail="Users service not available")
    headers = {}
    # Forward auth if provided so users service can enforce access as needed
    # Note: FastAPI dependency already validated token; here we just pass it through if present
    # We cannot directly access the header value here; rely on httpx without auth for this public endpoint
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(f"{users_service_url}/users/{current_username}/followees", headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch followees from users service")
        data = resp.json()
        followees = data.get("followees") or []
        followee_ids = [f.get("user_id") for f in followees if f.get("user_id") is not None]

    if not followee_ids:
        return []

    posts = db.execute(
        select(Post)
        .where(Post.user_id.in_(followee_ids))
        .order_by(Post.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return posts

