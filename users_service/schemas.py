from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    bio: str = ""
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr
    bio: str

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

