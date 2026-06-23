import sys
import types
from datetime import date
from datetime import datetime

import pytest
from sqlalchemy import Date
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects import registry
from sqlalchemy.engine import make_url

from gaussdb_sqlalchemy import jdbc_dbapi
from gaussdb_sqlalchemy.jdbc import GaussDBDialect_jdbc


def test_create_connect_args_builds_jdbc_url_and_properties():
    dialect = GaussDBDialect_jdbc()

    args, kwargs = dialect.create_connect_args(
        make_url(
            "gaussdb+jdbc://scott:tiger@db.example.com:8000/postgres"
            "?jdbc_driver_path=C:/drivers/gsjdbc4.jar&ssl=true"
        )
    )

    assert kwargs == {}
    assert args == [
        "com.huawei.gaussdb.jdbc.Driver",
        "jdbc:gaussdb://db.example.com:8000/postgres?ssl=true",
        {"user": "scott", "password": "tiger", "ssl": "true"},
        ["C:/drivers/gsjdbc4.jar"],
    ]


def test_create_connect_args_supports_custom_driver_class_and_jdbc_url():
    dialect = GaussDBDialect_jdbc()

    args, kwargs = dialect.create_connect_args(
        make_url(
            "gaussdb+jdbc://scott:tiger@ignored/postgres"
            "?jdbc_driver_class=org.postgresql.Driver"
            "&jdbc_driver_path=C:/drivers/postgresql.jar"
            "&jdbc_url=jdbc:postgresql://db.example.com:5432/postgres"
        )
    )

    assert kwargs == {}
    assert args == [
        "org.postgresql.Driver",
        "jdbc:postgresql://db.example.com:5432/postgres",
        {"user": "scott", "password": "tiger"},
        ["C:/drivers/postgresql.jar"],
    ]


def test_create_connect_args_builds_postgresql_url_for_postgresql_driver_class():
    dialect = GaussDBDialect_jdbc()

    args, kwargs = dialect.create_connect_args(
        make_url(
            "gaussdb+jdbc://scott:tiger@db.example.com:5432/postgres"
            "?jdbc_driver_class=org.postgresql.Driver"
            "&jdbc_driver_path=C:/drivers/postgresql.jar"
            "&ssl=true"
        )
    )

    assert kwargs == {}
    assert args == [
        "org.postgresql.Driver",
        "jdbc:postgresql://db.example.com:5432/postgres?ssl=true",
        {"user": "scott", "password": "tiger", "ssl": "true"},
        ["C:/drivers/postgresql.jar"],
    ]


def test_create_connect_args_requires_database_name():
    dialect = GaussDBDialect_jdbc()

    with pytest.raises(ValueError, match="database name is required"):
        dialect.create_connect_args(make_url("gaussdb+jdbc://localhost"))


def test_sqlalchemy_registry_can_load_jdbc_dialect():
    assert registry.load("gaussdb") is GaussDBDialect_jdbc
    assert registry.load("gaussdb.jdbc") is GaussDBDialect_jdbc


def test_current_timestamp_expression_compiles_without_parentheses():
    compiled = select(func.current_timestamp()).compile(
        dialect=GaussDBDialect_jdbc()
    )

    assert str(compiled) == "SELECT CURRENT_TIMESTAMP AS current_timestamp_1"


def test_jdbc_date_result_processor_converts_datetime_to_date():
    dialect = GaussDBDialect_jdbc()
    processor = dialect.type_descriptor(Date()).result_processor(dialect, None)

    assert processor(datetime(2026, 6, 18, 0, 0, 0)) == date(2026, 6, 18)
    assert processor(date(2026, 6, 18)) == date(2026, 6, 18)
    assert processor(None) is None


def test_jdbc_dbapi_loads_jaydebeapi_lazily(monkeypatch):
    module = types.ModuleType("jaydebeapi")
    calls = []

    class FakeJdbcConnection:
        def setAutoCommit(self, value):
            calls.append(value)

    class FakeConnection:
        jconn = FakeJdbcConnection()

    def connect(*args, **kwargs):
        return FakeConnection()

    module.connect = connect
    monkeypatch.setitem(sys.modules, "jaydebeapi", module)

    assert isinstance(jdbc_dbapi.connect("driver", "url"), FakeConnection)
    assert calls == [False]


def test_jdbc_dbapi_has_actionable_error_when_dependency_missing(monkeypatch):
    def missing_module(name):
        raise ModuleNotFoundError("No module named 'jaydebeapi'", name=name)

    monkeypatch.setattr(jdbc_dbapi, "import_module", missing_module)

    with pytest.raises(ModuleNotFoundError, match="JayDeBeApi JPype1"):
        jdbc_dbapi.connect()
