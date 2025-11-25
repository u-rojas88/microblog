import os
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import User, Follow
from .schemas import UserCreate, UserOut, TokenOut
from .auth import hash_password, verify_password, create_access_token, decode_token
from registry_service.client import register_service, deregister_service


app = FastAPI(title="Users Service")


@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    # Register with service registry
    port = os.getenv("PORT", "5100")
    base_url = f"http://localhost:{port}"
    await register_service("users", base_url)


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
    return str(payload["sub"])  # username


@app.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter((User.username == user_in.username) | (User.email == user_in.email)).first():
        raise HTTPException(status_code=400, detail="Username or email already registered")
    user = User(
        username=user_in.username,
        email=user_in.email,
        bio=user_in.bio or "",
        password_hash=hash_password(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/login", response_model=TokenOut)
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(subject=user.username)
    return TokenOut(access_token=token)


@app.get("/users/{username}", response_model=UserOut)
def get_user(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/users/follow/{username}")
def follow_user(username: str, current_username: str = Depends(get_current_username), db: Session = Depends(get_db)):
    if username == current_username:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    follower = db.query(User).filter(User.username == current_username).first()
    followee = db.query(User).filter(User.username == username).first()
    if not followee:
        raise HTTPException(status_code=404, detail="User not found")
    if db.query(Follow).filter(Follow.follower_id == follower.user_id, Follow.followee_id == followee.user_id).first():
        return {"status": "already_following"}
    db.add(Follow(follower_id=follower.user_id, followee_id=followee.user_id))
    db.commit()
    return {"status": "ok"}


@app.post("/users/unfollow/{username}")
def unfollow_user(username: str, current_username: str = Depends(get_current_username), db: Session = Depends(get_db)):
    follower = db.query(User).filter(User.username == current_username).first()
    followee = db.query(User).filter(User.username == username).first()
    if not followee:
        raise HTTPException(status_code=404, detail="User not found")
    q = db.query(Follow).filter(Follow.follower_id == follower.user_id, Follow.followee_id == followee.user_id)
    if not q.first():
        return {"status": "not_following"}
    q.delete()
    db.commit()
    return {"status": "ok"}


@app.get("/users/{username}/followees")
def list_followees(username: str, db: Session = Depends(get_db)):
    """
    Returns the list of users that the given username follows.
    Useful for the timelines service to build a home timeline without direct DB access.
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    follow_rows = db.query(Follow).filter(Follow.follower_id == user.user_id).all()
    if not follow_rows:
        return {"followees": []}
    followee_ids = [row.followee_id for row in follow_rows]
    followees = db.query(User).filter(User.user_id.in_(followee_ids)).all()
    # Return minimal data needed by timelines: user_id and username
    return {
        "followees": [{"user_id": u.user_id, "username": u.username} for u in followees]
    }

