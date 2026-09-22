"""Schemas de autenticacao."""

from pydantic import BaseModel, Field, field_validator

from api.schemas.user import UserResponse, _normalize_email


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)

    _email = field_validator("email")(_normalize_email)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(AccessTokenResponse):
    user: UserResponse
