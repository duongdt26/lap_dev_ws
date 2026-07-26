"""Request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Role = Literal["admin", "operator", "viewer"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserResponse(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool


class ProcessPayload(BaseModel):
    steps: list = Field(default_factory=list)
    updatedAt: str | None = None
