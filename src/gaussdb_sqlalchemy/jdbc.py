"""SQLAlchemy dialect using GaussDB JDBC through JayDeBeApi."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from sqlalchemy.dialects import registry
from sqlalchemy import types as sqltypes

from . import jdbc_dbapi
from .alembic import register_alembic_impl
from .base import GaussDBDialect


register_alembic_impl()


_CONTROL_KEYS = {
    "jdbc_driver_class",
    "jdbc_driver_path",
    "jdbc_url",
}


class _GaussDBJDBCDate(sqltypes.Date):
    def result_processor(self, dialect, coltype):
        def process(value):
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return value

        return process


class GaussDBDialect_jdbc(GaussDBDialect):
    """GaussDB dialect backed by a JDBC driver via JayDeBeApi."""

    driver = "jdbc"
    default_paramstyle = "qmark"
    supports_statement_cache = True
    colspecs = {
        **GaussDBDialect.colspecs,
        sqltypes.Date: _GaussDBJDBCDate,
    }

    @classmethod
    def import_dbapi(cls):
        return jdbc_dbapi

    def create_connect_args(self, url):
        opts = url.translate_connect_args(username="user", database="database")
        opts.update(url.query)

        driver_class = opts.pop("jdbc_driver_class", "com.huawei.gaussdb.jdbc.Driver")
        driver_path = opts.pop("jdbc_driver_path", None)
        jdbc_url = opts.pop("jdbc_url", None)

        if not jdbc_url:
            jdbc_url = self._build_jdbc_url(url, opts)

        properties: dict[str, Any] = {}
        user = opts.pop("user", None)
        password = opts.pop("password", None)
        if user is not None:
            properties["user"] = user
        if password is not None:
            properties["password"] = password

        properties.update(
            {
                key: value
                for key, value in opts.items()
                if key not in {"host", "port", "database", "dbname"}
            }
        )

        args: list[Any] = [driver_class, jdbc_url, properties]
        if driver_path:
            args.append(self._split_driver_path(driver_path))
        return args, {}

    def do_execute(self, cursor, statement, parameters, context=None):
        cursor.execute(statement, _convert_parameters(parameters))

    def do_executemany(self, cursor, statement, parameters, context=None):
        cursor.executemany(
            statement, [_convert_parameters(param_set) for param_set in parameters]
        )

    def do_rollback(self, dbapi_connection):
        try:
            dbapi_connection.rollback()
        except Exception as exc:
            if "autoCommit is enabled" not in str(exc):
                raise

    @staticmethod
    def _split_driver_path(driver_path):
        if isinstance(driver_path, (tuple, list)):
            return list(driver_path)
        # JDBC jar paths are most often supplied on Windows, where semicolon is
        # the path-list separator. Avoid splitting "C:/..." on POSIX test hosts.
        return [part for part in str(driver_path).split(";") if part]

    @staticmethod
    def _build_jdbc_url(url, opts: dict[str, Any]) -> str:
        host = opts.get("host") or url.host or "localhost"
        port = opts.get("port") or url.port
        database = opts.get("database") or opts.get("dbname") or url.database
        if not database:
            raise ValueError("A database name is required for gaussdb+jdbc URLs")

        authority = f"{host}:{port}" if port else str(host)
        jdbc_url = f"jdbc:gaussdb://{authority}/{database}"
        query = {
            key: value
            for key, value in url.query.items()
            if key not in _CONTROL_KEYS
            and key not in {"user", "password", "host", "port", "database", "dbname"}
        }
        if query:
            jdbc_url = _merge_query(jdbc_url, query)
        return jdbc_url


def _merge_query(jdbc_url: str, query: dict[str, Any]) -> str:
    parts = urlsplit(jdbc_url)
    current = dict(parse_qsl(parts.query, keep_blank_values=True))
    current.update(query)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(current), parts.fragment)
    )


def _convert_parameters(parameters):
    if parameters is None:
        return parameters
    if isinstance(parameters, tuple):
        return tuple(_convert_parameter(value) for value in parameters)
    if isinstance(parameters, list):
        return [_convert_parameter(value) for value in parameters]
    if isinstance(parameters, dict):
        return {
            key: _convert_parameter(value) for key, value in parameters.items()
        }
    return parameters


def _convert_parameter(value):
    if isinstance(value, datetime):
        jpype = _load_jpype()
        timestamp = jpype.JClass("java.sql.Timestamp")
        return timestamp.valueOf(value.strftime("%Y-%m-%d %H:%M:%S.%f"))
    if isinstance(value, date):
        jpype = _load_jpype()
        sql_date = jpype.JClass("java.sql.Date")
        return sql_date.valueOf(value.isoformat())
    if isinstance(value, Decimal):
        jpype = _load_jpype()
        big_decimal = jpype.JClass("java.math.BigDecimal")
        return big_decimal(str(value))
    if isinstance(value, (bytes, bytearray)):
        jpype = _load_jpype()
        signed_bytes = [byte if byte < 128 else byte - 256 for byte in value]
        return jpype.JArray(jpype.JByte)(signed_bytes)
    return value


def _load_jpype():
    return __import__("jpype")


dialect = GaussDBDialect_jdbc

registry.register(
    "gaussdb.jdbc", "gaussdb_sqlalchemy.jdbc", "GaussDBDialect_jdbc"
)
registry.register("gaussdb", "gaussdb_sqlalchemy.jdbc", "GaussDBDialect_jdbc")
