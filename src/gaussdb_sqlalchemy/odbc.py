"""SQLAlchemy dialect for GaussDB using the ODBC driver via pyodbc.

Connection string examples
--------------------------

DSN-less (recommended for first-time setup)::

    gaussdb+odbc://user:password@host:port/database?driver=GaussDB+ODBC+Driver&sslmode=disable

DSN (pre-configured in ODBC Data Source Administrator)::

    gaussdb+odbc://user:password@/database?dsn=GaussDB_Prod
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy.dialects import registry
from sqlalchemy import types as sqltypes

from . import odbc_dbapi
from .alembic import register_alembic_impl
from .base import GaussDBDialect, _GaussDBOdbcDate, _GaussDBOdbcBoolean


register_alembic_impl()


# Inherit PG colspecs and override Date/Boolean with ODBC-aware variants.
# This ensures that BOTH user-defined Column(Date) and reflected columns
# get the result processors that normalise ODBC driver returns.
_cspecs = dict(GaussDBDialect.colspecs)
_cspecs[sqltypes.Date] = _GaussDBOdbcDate
_cspecs[sqltypes.Boolean] = _GaussDBOdbcBoolean

# Query-string keys that are not forwarded as ODBC connection attributes.
_CONTROL_KEYS = {"driver", "dsn"}


class GaussDBDialect_odbc(GaussDBDialect):
    """GaussDB dialect backed by the GaussDB ODBC driver via pyodbc."""

    driver = "odbc"
    default_paramstyle = "qmark"
    supports_statement_cache = True
    colspecs = _cspecs

    @classmethod
    def import_dbapi(cls):
        return odbc_dbapi

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def create_connect_args(self, url):
        opts = url.translate_connect_args(username="user", database="database")
        opts.update(url.query)

        dsn = opts.pop("dsn", None)
        driver_name = opts.pop("driver", "GaussDB ODBC Driver")
        sslmode = opts.pop("sslmode", None)

        user = opts.pop("user", None)
        password = opts.pop("password", None)
        host = opts.pop("host", None)
        port = opts.pop("port", None)
        database = opts.pop("database", None) or opts.pop("dbname", None)

        # Build the ODBC connection string.
        parts: list[str] = []

        if dsn:
            parts.append(f"DSN={dsn}")
        else:
            parts.append(f"Driver={{{driver_name}}}")
            if host:
                parts.append(f"Server={host}")
            if port:
                parts.append(f"Port={port}")

        if database:
            parts.append(f"Database={database}")
        if user:
            parts.append(f"UID={user}")
        if password:
            parts.append(f"PWD={password}")
        if sslmode:
            parts.append(f"SSLmode={sslmode}")

        # Forward any remaining query parameters as ODBC attributes.
        for key, value in opts.items():
            parts.append(f"{key}={value}")

        conn_str = ";".join(parts) + ";"
        return ([conn_str], {})

    # ------------------------------------------------------------------
    # Execution — reuse enum-cast logic from base, adapted for qmark params
    # ------------------------------------------------------------------

    def do_execute(self, cursor, statement, parameters, context=None):
        statement = _cast_enum_placeholders(statement, context)
        cursor.execute(statement, _convert_parameters(parameters))

    def do_executemany(self, cursor, statement, parameters, context=None):
        statement = _cast_enum_placeholders(statement, context)
        cursor.executemany(
            statement,
            [_convert_parameters(p) for p in parameters],
        )


# ----------------------------------------------------------------------
# Enum cast helpers (driver-agnostic)
# ----------------------------------------------------------------------

def _cast_enum_placeholders(statement, context):
    """Append ``::enum_type`` casts to ``?`` placeholders for Enum columns."""
    casts = _enum_casts_by_position(context)
    if not casts:
        return statement

    output = []
    placeholder_index = 0
    in_single_quote = False
    in_double_quote = False
    index = 0
    while index < len(statement):
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < len(statement) else ""

        if char == "'" and not in_double_quote:
            output.append(char)
            if in_single_quote and next_char == "'":
                output.append(next_char)
                index += 2
                continue
            in_single_quote = not in_single_quote
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            output.append(char)
            index += 1
            continue

        if char == "?" and not in_single_quote and not in_double_quote:
            output.append("?")
            output.append(casts.get(placeholder_index, ""))
            placeholder_index += 1
            index += 1
            continue

        output.append(char)
        index += 1

    return "".join(output)


def _enum_casts_by_position(context):
    compiled = getattr(context, "compiled", None)
    positiontup = getattr(compiled, "positiontup", None)
    binds = getattr(compiled, "binds", None)
    if not positiontup or not binds:
        return {}

    casts = {}
    dialect = getattr(context, "dialect", None)
    for index, bind_name in enumerate(positiontup):
        bind = binds.get(bind_name)
        cast = _enum_cast_for_type(getattr(bind, "type", None), dialect)
        if cast:
            casts[index] = cast
    return casts


def _enum_cast_for_type(type_, dialect):
    if isinstance(type_, sqltypes.TypeDecorator):
        type_ = type_.impl
    if not isinstance(type_, sqltypes.Enum):
        return None
    if not getattr(type_, "native_enum", False) or not type_.name:
        return None
    return "::" + _format_enum_type_name(type_, dialect)


def _format_enum_type_name(type_, dialect):
    preparer = getattr(dialect, "identifier_preparer", None)
    if preparer is None:
        quote = lambda value: str(value)
        quote_schema = quote
    else:
        quote = preparer.quote
        quote_schema = preparer.quote_schema

    if type_.schema:
        return f"{quote_schema(type_.schema)}.{quote(type_.name)}"
    return quote(type_.name)


def _convert_parameters(parameters):
    """Convert Python parameters for pyodbc.

    pyodbc accepts native Python types directly — no type bridging
    needed.  The only adjustment is ensuring Decimal is passed as-is
    (pyodbc handles it natively) and bytes are passed directly.
    """
    if parameters is None:
        return parameters
    if isinstance(parameters, tuple):
        return tuple(_convert_parameter(v) for v in parameters)
    if isinstance(parameters, list):
        return [_convert_parameter(v) for v in parameters]
    if isinstance(parameters, dict):
        return {k: _convert_parameter(v) for k, v in parameters.items()}
    return parameters


def _convert_parameter(value):
    # pyodbc handles datetime, date, Decimal, bytes natively.
    # No conversion needed — this function exists as a hook for future
    # GaussDB-specific parameter adjustments.
    return value


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------

dialect = GaussDBDialect_odbc

registry.register(
    "gaussdb.odbc", "gaussdb_sqlalchemy.odbc", "GaussDBDialect_odbc"
)
# Make gaussdb:// default to ODBC
registry.register("gaussdb", "gaussdb_sqlalchemy.odbc", "GaussDBDialect_odbc")
