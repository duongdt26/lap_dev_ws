"""Authenticated robot telemetry and initial command API."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..database import session_factory
from ..dependencies import (
    SESSION_COOKIE,
    authenticate_session_token,
    get_current_user,
    require_roles,
)
from ..models import User
from ..ros_gateway import get_ros_gateway


router = APIRouter(prefix="/api", tags=["robot"])


class TeleopCommand(BaseModel):
    linearX: float = Field(ge=-1.0, le=1.0)
    angularZ: float = Field(ge=-3.0, le=3.0)


class NavGoal(BaseModel):
    x: float
    y: float
    yaw: float
    controllerId: str = ""


def _publish_stop() -> None:
    try:
        get_ros_gateway().publish_teleop(0.0, 0.0)
    except RuntimeError:
        pass


@router.get("/robot/status")
async def robot_status(_user: User = Depends(get_current_user)):
    _version, value = get_ros_gateway().telemetry.snapshot()
    return value


@router.post("/robot/teleop", status_code=204)
async def robot_teleop(
    command: TeleopCommand,
    _user: User = Depends(require_roles("admin", "operator")),
):
    try:
        get_ros_gateway().publish_teleop(command.linearX, command.angularZ)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/robot/stop", status_code=204)
async def robot_stop(_user: User = Depends(require_roles("admin", "operator"))):
    try:
        get_ros_gateway().publish_teleop(0.0, 0.0)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/navigation/goal")
async def navigation_goal(
    goal: NavGoal,
    _user: User = Depends(require_roles("admin", "operator")),
):
    try:
        result = get_ros_gateway().send_nav_goal(
            goal.x, goal.y, goal.yaw, goal.controllerId
        )
        return {"success": bool(result.success), "message": result.message}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/navigation/cancel")
async def navigation_cancel(_user: User = Depends(require_roles("admin", "operator"))):
    try:
        result = get_ros_gateway().cancel_nav()
        return {"success": bool(result.success), "message": result.message}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket):
    token = websocket.cookies.get(SESSION_COOKIE)
    with session_factory()() as db:
        user = authenticate_session_token(db, token)
    if user is None:
        await websocket.close(code=4401, reason="Chưa đăng nhập")
        return

    await websocket.accept()
    last_version = -1
    last_send = 0.0
    try:
        while True:
            version, value = get_ros_gateway().telemetry.snapshot()
            now = time.monotonic()
            if version != last_version or now - last_send >= 5.0:
                await websocket.send_json(value)
                last_version = version
                last_send = now
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/control")
async def control_socket(websocket: WebSocket):
    """Authenticated dead-man control channel for teleop commands."""
    token = websocket.cookies.get(SESSION_COOKIE)
    with session_factory()() as db:
        user = authenticate_session_token(db, token)
    if user is None or user.role not in {"admin", "operator"}:
        await websocket.close(code=4403, reason="Không có quyền điều khiển")
        return

    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            command_type = payload.get("type")
            if command_type == "teleop":
                command = TeleopCommand.model_validate(payload)
                get_ros_gateway().publish_teleop(command.linearX, command.angularZ)
                await websocket.send_json({"ok": True, "type": "teleop"})
            elif command_type == "stop":
                _publish_stop()
                await websocket.send_json({"ok": True, "type": "stop"})
            else:
                await websocket.send_json({"ok": False, "error": "Lệnh không hỗ trợ"})
    except WebSocketDisconnect:
        _publish_stop()
    except Exception:
        _publish_stop()
        try:
            await websocket.close(code=1011, reason="Control channel lỗi")
        except RuntimeError:
            pass
