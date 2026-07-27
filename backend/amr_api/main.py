"""AMR API, dashboard static server, and temporary rosbridge proxy."""

from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .dependencies import require_roles
from .legacy_import import import_legacy_data
from .migrations import upgrade_database
from .models import MapRecord, User
from .ros_gateway import get_ros_gateway
from .mode_manager import get_mode_manager
from .routers import auth, data, robot


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_database()
    if settings.import_legacy_on_start:
        from .database import session_factory

        with session_factory()() as db:
            map_count = db.scalar(select(func.count()).select_from(MapRecord))
            if not map_count:
                import_legacy_data(db, settings)
    gateway = get_ros_gateway(settings)
    gateway.start()
    yield
    get_mode_manager(settings).close()
    gateway.stop()


app = FastAPI(
    title="AMR Control API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )

app.include_router(auth.router)
app.include_router(data.router)
app.include_router(robot.router)


@app.get("/api/health", tags=["system"])
async def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    admin_count = db.scalar(
        select(func.count()).select_from(User).where(
            User.role == "admin", User.is_active.is_(True)
        )
    )
    _version, telemetry = get_ros_gateway().telemetry.snapshot()
    return {
        "status": "ok",
        "database": "ok",
        "adminConfigured": bool(admin_count),
        "ros": telemetry.get("ros", {}),
        "rosbridgeCompatibility": settings.enable_rosbridge_proxy,
        "mapsRoot": str(settings.maps_root.expanduser()),
    }


@app.get("/api/admin/config", tags=["system"])
async def visible_config(_admin: User = Depends(require_roles("admin"))):
    return {
        "databasePath": str(settings.db_path),
        "mapsRoot": str(settings.maps_root),
        "legacyDataRoot": str(settings.legacy_data_root),
        "writeLegacyFiles": settings.write_legacy_files,
        "importLegacyOnStart": settings.import_legacy_on_start,
        "useSimTime": settings.use_sim_time,
        "rosbridgeCompatibility": settings.enable_rosbridge_proxy,
    }


@app.websocket("/rosbridge")
async def rosbridge_proxy(websocket: WebSocket):
    """Temporary compatibility path; disable after the frontend migration."""
    if not settings.enable_rosbridge_proxy:
        await websocket.close(code=4404, reason="Rosbridge compatibility disabled")
        return
    await websocket.accept()
    try:
        from websockets.asyncio.client import connect

        async with connect(settings.rosbridge_url) as upstream:
            async def browser_to_ros() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                        else:
                            break
                except WebSocketDisconnect:
                    return

            async def ros_to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = {
                asyncio.create_task(browser_to_ros()),
                asyncio.create_task(ros_to_browser()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
    except Exception:
        try:
            await websocket.close(code=1011, reason="Không kết nối được rosbridge nội bộ")
        except RuntimeError:
            pass


@app.get("/{asset_path:path}", include_in_schema=False)
async def dashboard_asset(asset_path: str = ""):
    """Serve the small dashboard without AnyIO's sync threadpool."""
    root = settings.static_dir.resolve()
    requested = (root / (asset_path or "index.html")).resolve()
    if root != requested and root not in requested.parents:
        raise HTTPException(status_code=404)
    if requested.is_dir():
        requested = requested / "index.html"
    if not requested.is_file():
        raise HTTPException(status_code=404)
    media_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
    return Response(content=requested.read_bytes(), media_type=media_type)
