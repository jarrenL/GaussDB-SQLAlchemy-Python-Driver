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

    For psqlodbc (used as a stand-in when the GaussDB ODBC driver is not
    available), register an output converter for type -1 so that ``text``
    columns are decoded as UTF-8 strings instead of raising
    ``unsupported type 14``.
    """
    # Ensure autocommit is off — SQLAlchemy manages transactions.
    conn.autocommit = False

    # Register output converter for unknown/long types.
    # This is a no-op with the real GaussDB ODBC driver, but helps
    # psqlodbc handle GaussDB's text columns.
    try:
        def _text_converter(value):
            if isinstance(value, (bytes, bytearray)):
                return value.decode("utf-8")
            return str(value)

        conn.add_output_converter(-1, _text_converter)
    except Exception:
        pass  # Real GaussDB ODBC driver may not need this

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
