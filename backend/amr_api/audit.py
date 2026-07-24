"""Small helper for security and data-change audit events."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, User


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    resource: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            resource=resource,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )
