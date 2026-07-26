"""Validated SQLite storage with temporary JSON dual-write support."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import MapRecord


SAFE_MAP_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_map_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or not SAFE_MAP_RE.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Tên map không hợp lệ")
    return cleaned


def validate_process_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 128 or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=400, detail="Tên process không hợp lệ")
    return cleaned


def get_map(db: Session, map_name: str) -> MapRecord | None:
    return db.scalar(select(MapRecord).where(MapRecord.name == map_name))


def get_or_create_map(db: Session, settings: Settings, map_name: str) -> MapRecord:
    name = validate_map_name(map_name)
    record = get_map(db, name)
    if record is not None:
        return record
    yaml_path = settings.maps_root / f"{name}.yaml"
    image_path = settings.maps_root / f"{name}.pgm"
    record = MapRecord(
        name=name,
        yaml_path=str(yaml_path) if yaml_path.exists() else None,
        image_path=str(image_path) if image_path.exists() else None,
        metadata_json="{}",
    )
    db.add(record)
    db.flush()
    return record


def parse_json(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return fallback


def compact_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 2_000_000:
        raise HTTPException(status_code=413, detail="Dữ liệu vượt quá giới hạn 2 MB")
    return text


def _safe_process_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w-]", "_", name, flags=re.UNICODE)
    return cleaned or "process"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_legacy_setpoints(settings: Settings, map_name: str, points: list) -> None:
    if settings.write_legacy_files:
        _atomic_write_json(
            settings.legacy_data_root / map_name / "setpoint" / "setpoints.json",
            {"mapName": map_name, "setpoints": points},
        )


def write_legacy_process(
    settings: Settings, map_name: str, process_name: str, payload: dict
) -> None:
    if settings.write_legacy_files:
        value = {"name": process_name, **payload}
        _atomic_write_json(
            settings.legacy_data_root
            / map_name
            / "process"
            / f"{_safe_process_filename(process_name)}.json",
            value,
        )


def write_legacy_keepout(settings: Settings, map_name: str, zones: list) -> None:
    if settings.write_legacy_files:
        _atomic_write_json(
            settings.legacy_data_root
            / map_name
            / "keepout"
            / "keepout_zones.json",
            {"mapName": map_name, "zones": zones},
        )


def validate_setpoints(points: list) -> list:
    if len(points) > 5000:
        raise HTTPException(status_code=400, detail="Tối đa 5000 setpoint mỗi map")
    if not all(isinstance(point, dict) for point in points):
        raise HTTPException(status_code=400, detail="Setpoint phải là danh sách object")
    compact_json(points)
    return points


def validate_keepout(zones: list) -> list:
    if len(zones) > 100:
        raise HTTPException(status_code=400, detail="Tối đa 100 vùng cấm mỗi map")
    for index, zone in enumerate(zones, start=1):
        if not isinstance(zone, dict):
            raise HTTPException(status_code=400, detail=f"Vùng cấm #{index} không hợp lệ")
        points = zone.get("points", [])
        if not isinstance(points, list) or not 3 <= len(points) <= 200:
            raise HTTPException(
                status_code=400,
                detail=f"Vùng cấm #{index} phải có từ 3 đến 200 điểm",
            )
        for point in points:
            if not isinstance(point, dict) or "x" not in point or "y" not in point:
                raise HTTPException(
                    status_code=400, detail=f"Tọa độ vùng cấm #{index} không hợp lệ"
                )
            try:
                float(point["x"])
                float(point["y"])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"Tọa độ vùng cấm #{index} không hợp lệ"
                ) from None
    compact_json(zones)
    return zones
