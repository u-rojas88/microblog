from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl


class PostCreate(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    repost_original_url: HttpUrl | None = None


class PostOut(BaseModel):
    user_id: int
    username: str
    text: str
    created_at: datetime
    repost_original_url: str | None

    class Config:
        from_attributes = True

