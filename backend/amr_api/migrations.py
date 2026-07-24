"""Programmatic Alembic runner used on application startup."""

from alembic import command
from alembic.config import Config

from .config import PROJECT_ROOT, get_settings


def upgrade_database() -> None:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
