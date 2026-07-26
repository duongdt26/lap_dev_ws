"""Environment based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    maps_root: Path
    legacy_data_root: Path
    write_legacy_files: bool
    import_legacy_on_start: bool
    static_dir: Path
    session_ttl_seconds: int
    cookie_secure: bool
    enable_rosbridge_proxy: bool
    rosbridge_url: str
    enable_ros_gateway: bool
    use_sim_time: bool
    cors_origins: tuple[str, ...]

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


def get_settings() -> Settings:
    origins = tuple(
        item.strip()
        for item in os.getenv("AMR_CORS_ORIGINS", "").split(",")
        if item.strip()
    )
    return Settings(
        host=os.getenv("AMR_API_HOST", "0.0.0.0"),
        port=int(os.getenv("AMR_API_PORT", "8080")),
        db_path=_path("AMR_DB_PATH", "~/amr_data/amr.sqlite3"),
        maps_root=_path("AMR_MAPS_ROOT", "~/maps"),
        legacy_data_root=_path("AMR_LEGACY_DATA_ROOT", "~/MAP_DATA"),
        write_legacy_files=_bool("AMR_WRITE_LEGACY_FILES", True),
        import_legacy_on_start=_bool("AMR_IMPORT_LEGACY_ON_START", True),
        static_dir=_path(
            "AMR_STATIC_DIR", str(PROJECT_ROOT / "web" / "amr_dashboard")
        ),
        session_ttl_seconds=max(
            300, int(os.getenv("AMR_SESSION_TTL_SECONDS", "28800"))
        ),
        cookie_secure=_bool("AMR_COOKIE_SECURE", False),
        enable_rosbridge_proxy=_bool("AMR_ENABLE_ROSBRIDGE_PROXY", True),
        rosbridge_url=os.getenv(
            "AMR_ROSBRIDGE_URL", "ws://127.0.0.1:9090"
        ),
        enable_ros_gateway=_bool("AMR_ENABLE_ROS_GATEWAY", True),
        use_sim_time=_bool("AMR_USE_SIM_TIME", False),
        cors_origins=origins,
    )
