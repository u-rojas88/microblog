import os
import json
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, Header, Query
import greenstalk

from .db import get_redis
from .auth import decode_token
from .schemas import LikeActionResult, LikeCount, UserLikes, PopularPosts
from registry_service.client import register_service, deregister_service
from registry_service.discovery import get_service_url_sync


app = FastAPI(title="Likes Service")

# Beanstalkd configuration
BEANSTALKD_HOST = os.getenv("BEANSTALKD_HOST", "127.0.0.1")
BEANSTALKD_PORT = int(os.getenv("BEANSTALKD_PORT", "11300"))
LIKE_VALIDATION_QUEUE = "like_validation"
LIKE_NOTIFICATION_QUEUE = "like_notification"


@app.on_event("startup")
async def on_startup():
    # Register with service registry
    port = os.getenv("PORT", "5400")
    base_url = f"http://localhost:{port}"
    await register_service("likes", base_url)


@app.on_event("shutdown")
async def on_shutdown():
    # Deregister from service registry
    await deregister_service()


def get_current_username(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return str(payload["sub"])


def likes_key_for_post(post_id: int) -> str:
    return f"likes:post:{post_id}"


def likes_key_for_user(username: str) -> str:
    return f"likes:user:{username}"


def likes_score_key() -> str:
    return "likes:score"


@app.post("/likes/{post_id}", response_model=LikeActionResult)
def like_post(post_id: int, current_username: str = Depends(get_current_username)):
    r = get_redis()
    # Add like; only increment popularity if this is a new like
    added = r.sadd(likes_key_for_post(post_id), current_username)
    r.sadd(likes_key_for_user(current_username), post_id)
    if added == 1:
        r.zincrby(likes_score_key(), 1, str(post_id))
        
        # Queue validation job to verify post exists
        validation_job = {
            "post_id": post_id,
            "username": current_username,
        }
        try:
            with greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT)) as client:
                client.use(LIKE_VALIDATION_QUEUE)
                client.put(json.dumps(validation_job))
        except Exception as e:
            # Log error but don't fail the like operation
            print(f"Failed to queue validation job: {e}", file=__import__("sys").stderr)
        
        # Queue notification job to notify post author
        notification_job = {
            "post_id": post_id,
            "liker_username": current_username,
        }
        try:
            with greenstalk.Client((BEANSTALKD_HOST, BEANSTALKD_PORT)) as client:
                client.use(LIKE_NOTIFICATION_QUEUE)
                client.put(json.dumps(notification_job))
        except Exception as e:
            # Log error but don't fail the like operation
            print(f"Failed to queue notification job: {e}", file=__import__("sys").stderr)
    
    return LikeActionResult(status="ok", liked=True, post_id=post_id)


@app.delete("/likes/{post_id}", response_model=LikeActionResult)
def unlike_post(post_id: int, current_username: str = Depends(get_current_username)):
    r = get_redis()
    removed = r.srem(likes_key_for_post(post_id), current_username)
    r.srem(likes_key_for_user(current_username), post_id)
    if removed == 1:
        r.zincrby(likes_score_key(), -1, str(post_id))
        # Optionally clean up if score reaches 0
        score = r.zscore(likes_score_key(), str(post_id))
        if score is not None and score <= 0:
            r.zrem(likes_score_key(), str(post_id))
    return LikeActionResult(status="ok", liked=False, post_id=post_id)


@app.get("/likes/{post_id}/count", response_model=LikeCount)
def count_likes(post_id: int):
    r = get_redis()
    count = r.scard(likes_key_for_post(post_id))
    return LikeCount(post_id=post_id, likes=count)


@app.get("/users/{username}/likes", response_model=UserLikes)
def list_user_likes(username: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    r = get_redis()
    # Fetch all post IDs; Redis sets are unordered, so we return an arbitrary order with optional pagination
    post_ids = list(r.smembers(likes_key_for_user(username)))
    # Convert to ints and apply pagination
    post_ids_int = [int(pid) for pid in post_ids]
    sliced = post_ids_int[offset: offset + limit]
    return UserLikes(username=username, post_ids=sliced)


@app.get("/likes/popular", response_model=PopularPosts)
def popular_posts(limit: int = Query(50, ge=1, le=200)):
    r = get_redis()
    # Highest scores first
    ranked = r.zrevrange(likes_score_key(), 0, limit - 1, withscores=False)
    post_ids = [int(pid) for pid in ranked]
    return PopularPosts(post_ids=post_ids)


