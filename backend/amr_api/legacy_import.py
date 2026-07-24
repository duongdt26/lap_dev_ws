"""One-way importer from ~/maps and ~/MAP_DATA into SQLite."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .data_store import compact_json, get_or_create_map
from .models import KeepoutCollection, ProcessRecord, SetpointCollection


def _read_json(path: Path, fallback):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return fallback


def import_legacy_data(db: Session, settings: Settings) -> dict[str, int]:
    names = {path.stem for path in settings.maps_root.glob("*.yaml")}
    if settings.legacy_data_root.is_dir():
        names.update(path.name for path in settings.legacy_data_root.iterdir() if path.is_dir())

    counts = {"maps": 0, "setpoints": 0, "processes": 0, "keepout": 0}
    for map_name in sorted(names):
        try:
            record = get_or_create_map(db, settings, map_name)
        except Exception:
            continue
        counts["maps"] += 1
        root = settings.legacy_data_root / map_name

        setpoint_path = root / "setpoint" / "setpoints.json"
        if setpoint_path.is_file():
            raw = _read_json(setpoint_path, [])
            points = raw.get("setpoints", []) if isinstance(raw, dict) else raw
            if isinstance(points, list):
                value = db.scalar(
                    select(SetpointCollection).where(SetpointCollection.map_id == record.id)
                )
                if value is None:
                    value = SetpointCollection(map_id=record.id)
                    db.add(value)
                value.payload_json = compact_json(points)
                counts["setpoints"] += len(points)

        process_dir = root / "process"
        if process_dir.is_dir():
            for path in sorted(process_dir.glob("*.json")):
                payload = _read_json(path, {})
                if not isinstance(payload, dict):
                    continue
                name = str(payload.get("name") or path.stem).strip()
                if not name:
                    continue
                value = db.scalar(
                    select(ProcessRecord).where(
                        ProcessRecord.map_id == record.id,
                        ProcessRecord.name == name,
                    )
                )
                if value is None:
                    value = ProcessRecord(map_id=record.id, name=name)
                    db.add(value)
                value.payload_json = compact_json(payload)
                counts["processes"] += 1

        keepout_path = root / "keepout" / "keepout_zones.json"
        if keepout_path.is_file():
            raw = _read_json(keepout_path, [])
            zones = raw.get("zones", []) if isinstance(raw, dict) else raw
            if isinstance(zones, list):
                value = db.scalar(
                    select(KeepoutCollection).where(KeepoutCollection.map_id == record.id)
                )
                if value is None:
                    value = KeepoutCollection(map_id=record.id)
                    db.add(value)
                value.payload_json = compact_json(zones)
                counts["keepout"] += len(zones)

    db.commit()
    return counts
