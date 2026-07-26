"""Administrative commands that avoid putting passwords in source files."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .database import session_factory
from .legacy_import import import_legacy_data
from .migrations import upgrade_database
from .models import User
from .security import hash_password


def _password(confirm: bool = True) -> str:
    value = getpass.getpass("Mật khẩu: ")
    if confirm and value != getpass.getpass("Nhập lại mật khẩu: "):
        raise ValueError("Hai mật khẩu không giống nhau")
    return value


def _create_user(username: str, role: str, update: bool = False) -> None:
    upgrade_database()
    with session_factory()() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is not None and not update:
            raise ValueError(f"Tài khoản {username!r} đã tồn tại")
        password_hash = hash_password(_password())
        if user is None:
            user = User(
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
            )
            db.add(user)
        else:
            user.password_hash = password_hash
            user.role = role
            user.is_active = True
        db.commit()
    print(f"Đã lưu tài khoản {username!r} với quyền {role}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quản trị AMR API")
    commands = parser.add_subparsers(dest="command", required=True)

    init_db = commands.add_parser("init-db", help="Tạo/nâng cấp schema SQLite")
    init_db.set_defaults(handler=lambda _args: upgrade_database())

    create = commands.add_parser("create-user", help="Tạo tài khoản")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=("admin", "operator", "viewer"), default="viewer")
    create.set_defaults(handler=lambda args: _create_user(args.username, args.role))

    password = commands.add_parser("reset-password", help="Đổi mật khẩu và mở lại tài khoản")
    password.add_argument("--username", required=True)
    password.add_argument("--role", choices=("admin", "operator", "viewer"), default="admin")
    password.set_defaults(
        handler=lambda args: _create_user(args.username, args.role, update=True)
    )

    importer = commands.add_parser("import-legacy", help="Nhập ~/maps và ~/MAP_DATA vào SQLite")

    def do_import(_args) -> None:
        upgrade_database()
        with session_factory()() as db:
            counts = import_legacy_data(db, get_settings())
        print(
            "Đã nhập: "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
        )

    importer.set_defaults(handler=do_import)

    args = parser.parse_args()
    try:
        args.handler(args)
    except ValueError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
