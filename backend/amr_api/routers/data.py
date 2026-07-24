"""Authenticated CRUD API for map-related persistent data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..data_store import (
    compact_json,
    get_map,
    get_or_create_map,
    parse_json,
    validate_keepout,
    validate_map_name,
    validate_process_name,
    validate_setpoints,
    write_legacy_keepout,
    write_legacy_process,
    write_legacy_setpoints,
)
from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import KeepoutCollection, MapRecord, ProcessRecord, SetpointCollection, User


router = APIRouter(prefix="/api", tags=["map data"])
can_read = Depends(get_current_user)
can_write = Depends(require_roles("admin", "operator"))


def _require_map(db: Session, map_name: str) -> MapRecord:
    name = validate_map_name(map_name)
    record = get_map(db, name)
    if record is None:
        raise HTTPException(status_code=404, detail="Map chưa có trong database")
    return record


@router.get("/maps")
async def list_maps(_user: User = can_read, db: Session = Depends(get_db)):
    records = db.scalars(select(MapRecord).order_by(MapRecord.name)).all()
    return [
        {
            "name": item.name,
            "yamlPath": item.yaml_path,
            "imagePath": item.image_path,
            "metadata": parse_json(item.metadata_json, {}),
        }
        for item in records
    ]


@router.put("/maps/{map_name}")
async def upsert_map(
    map_name: str,
    metadata: dict[str, Any] = Body(default_factory=dict),
    user: User = can_write,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    existed = get_map(db, validate_map_name(map_name)) is not None
    record = get_or_create_map(db, settings, map_name)
    if metadata or not existed:
        record.metadata_json = compact_json(metadata)
    write_audit(db, user, "map.updated", f"map:{record.name}")
    db.commit()
    return {"name": record.name, "metadata": metadata}


@router.get("/maps/{map_name}/setpoints")
async def get_setpoints(map_name: str, _user: User = can_read, db: Session = Depends(get_db)):
    record = _require_map(db, map_name)
    value = db.scalar(
        select(SetpointCollection).where(SetpointCollection.map_id == record.id)
    )
    return parse_json(value.payload_json, []) if value else []


@router.put("/maps/{map_name}/setpoints")
async def put_setpoints(
    map_name: str,
    points: list[dict[str, Any]],
    user: User = can_write,
    db: Session = Depends(get_db),
):
    points = validate_setpoints(points)
    settings = get_settings()
    record = get_or_create_map(db, settings, map_name)
    value = db.scalar(
        select(SetpointCollection).where(SetpointCollection.map_id == record.id)
    )
    if value is None:
        value = SetpointCollection(map_id=record.id)
        db.add(value)
    value.payload_json = compact_json(points)
    write_legacy_setpoints(settings, record.name, points)
    write_audit(db, user, "setpoints.updated", f"map:{record.name}", {"count": len(points)})
    db.commit()
    return {"success": True, "count": len(points)}


@router.get("/maps/{map_name}/processes")
async def list_processes(map_name: str, _user: User = can_read, db: Session = Depends(get_db)):
    record = _require_map(db, map_name)
    values = db.scalars(
        select(ProcessRecord)
        .where(ProcessRecord.map_id == record.id)
        .order_by(ProcessRecord.name)
    ).all()
    return [item.name for item in values]


@router.get("/maps/{map_name}/processes/{process_name}")
async def get_process(
    map_name: str,
    process_name: str,
    _user: User = can_read,
    db: Session = Depends(get_db),
):
    record = _require_map(db, map_name)
    name = validate_process_name(process_name)
    value = db.scalar(
        select(ProcessRecord).where(
            ProcessRecord.map_id == record.id, ProcessRecord.name == name
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy process")
    return parse_json(value.payload_json, {})


@router.put("/maps/{map_name}/processes/{process_name}")
async def put_process(
    map_name: str,
    process_name: str,
    payload: dict[str, Any],
    user: User = can_write,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    record = get_or_create_map(db, settings, map_name)
    name = validate_process_name(process_name)
    if not isinstance(payload.get("steps", []), list):
        raise HTTPException(status_code=400, detail="steps phải là một danh sách")
    value = db.scalar(
        select(ProcessRecord).where(
            ProcessRecord.map_id == record.id, ProcessRecord.name == name
        )
    )
    if value is None:
        value = ProcessRecord(map_id=record.id, name=name)
        db.add(value)
    value.payload_json = compact_json(payload)
    write_legacy_process(settings, record.name, name, payload)
    write_audit(db, user, "process.updated", f"map:{record.name}/process:{name}")
    db.commit()
    return {"success": True, "name": name}


@router.delete("/maps/{map_name}/processes/{process_name}", status_code=204)
async def delete_process(
    map_name: str,
    process_name: str,
    user: User = can_write,
    db: Session = Depends(get_db),
):
    record = _require_map(db, map_name)
    name = validate_process_name(process_name)
    result = db.execute(
        delete(ProcessRecord).where(
            ProcessRecord.map_id == record.id, ProcessRecord.name == name
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy process")
    write_audit(db, user, "process.deleted", f"map:{record.name}/process:{name}")
    db.commit()
    return Response(status_code=204)


@router.get("/maps/{map_name}/keepout")
async def get_keepout(map_name: str, _user: User = can_read, db: Session = Depends(get_db)):
    record = _require_map(db, map_name)
    value = db.scalar(
        select(KeepoutCollection).where(KeepoutCollection.map_id == record.id)
    )
    return parse_json(value.payload_json, []) if value else []


@router.put("/maps/{map_name}/keepout")
async def put_keepout(
    map_name: str,
    zones: list[dict[str, Any]],
    user: User = can_write,
    db: Session = Depends(get_db),
):
    zones = validate_keepout(zones)
    settings = get_settings()
    record = get_or_create_map(db, settings, map_name)
    value = db.scalar(
        select(KeepoutCollection).where(KeepoutCollection.map_id == record.id)
    )
    if value is None:
        value = KeepoutCollection(map_id=record.id)
        db.add(value)
    value.payload_json = compact_json(zones)
    write_legacy_keepout(settings, record.name, zones)
    write_audit(db, user, "keepout.updated", f"map:{record.name}", {"count": len(zones)})
    db.commit()
    return {"success": True, "count": len(zones), "appliedToRos": False}
