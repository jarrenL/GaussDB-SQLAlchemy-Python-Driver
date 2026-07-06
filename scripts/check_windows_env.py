"""Check whether the local Python environment can load the GaussDB ODBC driver."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from urllib.parse import parse_qsl
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


def _mask_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.password:
        return url
    username = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{username}:***@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _check_import(module_name: str) -> object | None:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        print(f"[FAIL] import {module_name}: {type(exc).__name__}: {exc}")
        return None

    version = getattr(module, "__version__", "unknown")
    print(f"[ OK ] import {module_name}: {version}")
    return module


def _check_odbc_drivers() -> list[str]:
    """List installed ODBC drivers (best effort)."""
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        if drivers:
            print(f"[ OK ] ODBC drivers found: {len(drivers)}")
            for d in drivers:
                if "gauss" in d.lower() or "postgres" in d.lower():
                    print(f"       * {d}")
            return drivers
        else:
            print("[WARN] No ODBC drivers registered in the system.")
            return []
    except Exception as exc:
        print(f"[WARN] Could not list ODBC drivers: {exc}")
        return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check GaussDB ODBC and SQLAlchemy driver availability."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GAUSSDB_TEST_URL"),
        help="Optional SQLAlchemy URL used for a live select 1 check.",
    )
    args = parser.parse_args()

    print(f"Python: {sys.version.split()[0]}")
    print(f"Executable: {sys.executable}")
    print(f"Platform: {sys.platform}")
    print(f"PATH: {os.environ.get('PATH', '')}")

    sqlalchemy = _check_import("sqlalchemy")
    dialect = _check_import("gaussdb_sqlalchemy")
    pyodbc = _check_import("pyodbc")

    if pyodbc:
        _check_odbc_drivers()

    if not all((sqlalchemy, dialect, pyodbc)):
        print()
        print("请确认已安装 pyodbc、SQLAlchemy 和本项目 wheel。")
        print("还需要安装 GaussDB ODBC 驱动。")
        return 1

    if not args.url:
        print("[SKIP] 未提供 --url 或 GAUSSDB_TEST_URL，跳过真实连接检查。")
        return 0

    from sqlalchemy import create_engine
    from sqlalchemy import text

    print(f"Connecting: {_mask_url(args.url)}")
    try:
        engine = create_engine(args.url, pool_pre_ping=True)
        with engine.connect() as conn:
            value = conn.execute(text("select 1")).scalar_one()
    except Exception as exc:
        print(f"[FAIL] live connection: {type(exc).__name__}: {exc}")
        return 2

    print(f"[ OK ] live connection: select 1 -> {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
