from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    factory_code: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str
    confirm_new_password: str


class LoginOk(BaseModel):
    message: str = "logged_in"


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: Optional[str] = None
    department: Optional[str] = None
    department_code: Optional[str] = None
    extra_permissions: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    factory_code: str = "MIL"
    assigned_factory_code: str = "MIL"
    available_factories: list[str] = Field(default_factory=list)
