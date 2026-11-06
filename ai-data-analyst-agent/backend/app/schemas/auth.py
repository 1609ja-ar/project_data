from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


def _check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(v) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        raise ValueError("Password must contain letters and numbers")
    return v


class SignupIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class SigninIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _check_password(v)


class UpdateMeIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    ai_provider: Literal["groq", "xai"] | None = None
    allow_ai_samples: bool | None = None
    clear_ai_provider: bool = False


class DeleteMeIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def public_user(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "full_name": u["full_name"],
        "email": u["email"],
        "email_verified": u.get("email_verified", False),
        "ai_provider": u.get("ai_provider"),
        "allow_ai_samples": u.get("allow_ai_samples", False),
        "created_at": u["created_at"].isoformat(),
    }
