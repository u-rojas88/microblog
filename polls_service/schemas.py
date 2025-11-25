from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, conlist, validator


class PollCreate(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    options: conlist(str, min_length=2, max_length=4)


class PollOut(BaseModel):
    poll_id: str
    question: str
    options: List[str]
    counts: List[int] = Field(description="Vote counts per option, same order as options")
    created_by: str
    created_at: datetime


class VoteIn(BaseModel):
    choice_index: int = Field(ge=0, le=3, description="Index in options (0..3)")

    @validator("choice_index")
    def validate_choice(cls, v):
        return v


class VoteResult(BaseModel):
    status: str
    poll: PollOut


