"""End-to-end checks for authentication, roles and SQLite CRUD."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="amr_api_pytest_"))
os.environ["AMR_DB_PATH"] = str(TEST_ROOT / "test.sqlite3")
os.environ["AMR_MAPS_ROOT"] = str(TEST_ROOT / "maps")
os.environ["AMR_LEGACY_DATA_ROOT"] = str(TEST_ROOT / "legacy")
os.environ["AMR_ENABLE_ROS_GATEWAY"] = "false"
os.environ["AMR_ENABLE_ROSBRIDGE_PROXY"] = "false"
os.environ["AMR_IMPORT_LEGACY_ON_START"] = "false"

import httpx  # noqa: E402

from backend.amr_api.database import session_factory  # noqa: E402
from backend.amr_api.main import app  # noqa: E402
from backend.amr_api.models import User  # noqa: E402
from backend.amr_api.security import hash_password  # noqa: E402


def test_auth_roles_and_map_data() -> None:
    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            with session_factory()() as db:
                db.add(
                    User(
                        username="admin",
                        password_hash=hash_password("AdminPassword123!"),
                        role="admin",
                        is_active=True,
                    )
                )
                db.commit()

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                assert (await client.get("/api/health")).status_code == 200
                assert (await client.get("/")).status_code == 200
                assert (await client.get("/api/auth/me")).status_code == 401
                assert (
                    await client.post(
                        "/api/auth/login",
                        json={"username": "admin", "password": "wrong"},
                    )
                ).status_code == 401

                response = await client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "AdminPassword123!"},
                )
                assert response.status_code == 200
                assert response.json()["role"] == "admin"

                response = await client.post(
                    "/api/admin/users",
                    json={
                        "username": "viewer01",
                        "password": "ViewerPassword123!",
                        "role": "viewer",
                    },
                )
                assert response.status_code == 201

                points = [{"id": "P1", "name": "Dock", "x": 1.2, "y": -0.3}]
                response = await client.put(
                    "/api/maps/test_map/setpoints", json=points
                )
                assert response.status_code == 200
                assert response.json()["count"] == 1
                assert (
                    await client.get("/api/maps/test_map/setpoints")
                ).json() == points
                legacy_setpoints = (
                    TEST_ROOT / "legacy" / "test_map" / "setpoint" / "setpoints.json"
                )
                assert legacy_setpoints.is_file()

                process = {"steps": ["P1"]}
                assert (
                    await client.put(
                        "/api/maps/test_map/processes/demo", json=process
                    )
                ).status_code == 200
                assert (
                    await client.get("/api/maps/test_map/processes/demo")
                ).json() == process

                invalid_zone = [{"name": "bad", "points": [{"x": 0, "y": 0}]}]
                assert (
                    await client.put(
                        "/api/maps/test_map/keepout", json=invalid_zone
                    )
                ).status_code == 400

                assert (await client.post("/api/auth/logout")).status_code == 204
                assert (
                    await client.post(
                        "/api/auth/login",
                        json={
                            "username": "viewer01",
                            "password": "ViewerPassword123!",
                        },
                    )
                ).status_code == 200
                assert (
                    await client.get("/api/maps/test_map/setpoints")
                ).status_code == 200
                assert (
                    await client.put("/api/maps/test_map/setpoints", json=points)
                ).status_code == 403

    asyncio.run(scenario())
