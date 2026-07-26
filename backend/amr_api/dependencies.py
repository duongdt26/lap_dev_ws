"""FastAPI authentication and authorization dependencies."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import LoginSession, User
from .security import hash_session_token


SESSION_COOKIE = "amr_session"


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def authenticate_session_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    now = int(time.time())
    login_session = db.scalar(
        select(LoginSession).where(
            LoginSession.token_hash == hash_session_token(token),
            LoginSession.expires_at > now,
        )
    )
    if login_session is None or not login_session.user.is_active:
        return None
    return login_session.user


async def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    token = _request_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập",
        )

    now = int(time.time())
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    user = authenticate_session_token(db, token)
    if user is None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
        )
    return user


def require_roles(*roles: str) -> Callable:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản không có quyền thực hiện thao tác này",
            )
        return user

    return dependency
