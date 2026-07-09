"""DB-API bridge to pyodbc for GaussDB ODBC connections.

This module wraps pyodbc so it conforms to the DB-API 2.0 interface that
SQLAlchemy expects, and applies GaussDB-specific connection settings.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any

_DBAPI_MODULE = "pyodbc"

# Cache the loaded module so exception classes are stable references.
_dbapi: ModuleType | None = None


def _load_dbapi() -> ModuleType:
    """Import pyodbc lazily so the dialect can be registered without it."""
    global _dbapi
    if _dbapi is not None:
        return _dbapi
    try:
        _dbapi = import_module(_DBAPI_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == _DBAPI_MODULE:
            raise ModuleNotFoundError(
                "pyodbc is not installed. Install it with 'pip install pyodbc'."
            ) from exc
        raise
    return _dbapi


def _patch_connection(conn):
    """Apply GaussDB-specific settings to a pyodbc connection.

    Registers output converters to normalise values that pyodbc / the
    GaussDB ODBC driver returns in formats different from what
    SQLAlchemy's PostgreSQL dialect expects.
    """
    # Ensure autocommit is off — SQLAlchemy manages transactions.
    conn.autocommit = False

    # Type 16 = BOO (boolean).  Some ODBC drivers return '1'/'0' or
    # b'\x01'/b'\x00' instead of Python True/False.
    def _bool_converter(value):
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return value.strip() in ("1", "t", "true", "T", "TRUE")
        return bool(value)
    try:
        conn.add_output_converter(16, _bool_converter)
    except Exception:
        pass

    # Type 1082 = DATE.  Some ODBC drivers (especially on Windows)
    # return a datetime.datetime instead of datetime.date.
    import datetime as _dt
    def _date_converter(value):
        if isinstance(value, _dt.datetime):
            return value.date()
        if isinstance(value, (bytes, bytearray)):
            s = value.decode("utf-8").strip()
            return _dt.date.fromisoformat(s)
        if isinstance(value, str):
            return _dt.date.fromisoformat(value.strip())
        return value
    try:
        conn.add_output_converter(1082, _date_converter)
    except Exception:
        pass

    # Type 25 = TEXT.  Some drivers return bytes; also normalise
    # Windows CRLF to LF so round-trip comparisons work.
    def _text_converter(value):
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8").replace("\r\n", "\n")
        if isinstance(value, str):
            return value.replace("\r\n", "\n")
        return str(value)
    try:
        conn.add_output_converter(25, _text_converter)
    except Exception:
        pass

    # Type -1 = unknown/long types — decode as UTF-8 text.
    try:
        conn.add_output_converter(-1, _text_converter)
    except Exception:
        pass

    return conn


def connect(connection_string: str, **kwargs: Any):
    """Open an ODBC connection to GaussDB.

    Parameters
    ----------
    connection_string:
        Full ODBC connection string, e.g.::

            Driver={GaussDB ODBC Driver};
            Server=host;Port=port;Database=db;
            UID=user;PWD=password;SSLmode=disable;

    **kwargs:
        Additional keyword arguments passed through to ``pyodbc.connect``.
    """
    dbapi = _load_dbapi()
    conn = dbapi.connect(connection_string, **kwargs)
    return _patch_connection(conn)


def __getattr__(name: str) -> Any:
    """Proxy attribute access to the underlying pyodbc module.

    This exposes DB-API exception classes (Error, OperationalError, etc.)
    and constants (NUMBER, STRING, ...) so SQLAlchemy sees a compliant
    DB-API module.
    """
    return getattr(_load_dbapi(), name)


# DB-API 2.0 module-level attributes
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"
