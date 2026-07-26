"""Login, logout and account-management endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..database import get_db
from ..dependencies import SESSION_COOKIE, get_current_user, require_roles
from ..models import LoginSession, User, utcnow
from ..schemas import (
    ChangePasswordRequest,
    LoginRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from ..security import (
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_password,
)


router = APIRouter(prefix="/api", tags=["authentication"])


def _response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/auth/login", response_model=UserResponse)
async def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not user.is_active or not verify_password(
        user.password_hash, payload.password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu",
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    raw_token = new_session_token()
    settings = get_settings()
    db.add(
        LoginSession(
            token_hash=hash_session_token(raw_token),
            user_id=user.id,
            expires_at=int(time.time()) + settings.session_ttl_seconds,
        )
    )
    user.last_login_at = utcnow()
    write_audit(db, user, "auth.login", f"user:{user.id}")
    db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return _response(user)


@router.post("/auth/logout", status_code=204)
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    write_audit(db, user, "auth.logout", f"user:{user.id}")
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _response(user)


@router.post("/auth/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng")
    user.password_hash = hash_password(payload.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    write_audit(db, user, "auth.password_changed", f"user:{user.id}")
    db.commit()


@router.get("/admin/users", response_model=list[UserResponse])
async def list_users(
    _admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    return [_response(user) for user in db.scalars(select(User).order_by(User.username))]


@router.post("/admin/users", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="Tên tài khoản đã tồn tại")
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    write_audit(db, admin, "admin.user_created", f"user:{user.id}", {"role": user.role})
    db.commit()
    return _response(user)


@router.patch("/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Không thể tự vô hiệu hóa tài khoản")
    if payload.role is not None:
        if user.role == "admin" and payload.role != "admin":
            admin_count = db.scalar(
                select(func.count()).select_from(User).where(
                    User.role == "admin", User.is_active.is_(True)
                )
            )
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="Phải còn ít nhất một admin")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    write_audit(db, admin, "admin.user_updated", f"user:{user.id}")
    db.commit()
    return _response(user)
