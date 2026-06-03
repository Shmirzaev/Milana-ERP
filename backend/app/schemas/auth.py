from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str
    confirm_new_password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Optional[str] = None
    department: Optional[str] = None
    permissions: list[str] = []
