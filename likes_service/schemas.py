from pydantic import BaseModel, Field
from typing import List


class LikeActionResult(BaseModel):
    status: str = Field(description="Result of the like/unlike action")
    liked: bool = Field(description="Whether the post is liked by the user after the action")
    post_id: int


class LikeCount(BaseModel):
    post_id: int
    likes: int


class UserLikes(BaseModel):
    username: str
    post_ids: List[int]


class PopularPosts(BaseModel):
    post_ids: List[int]


