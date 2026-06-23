from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import func
from sqlalchemy.schema import CreateIndex

from gaussdb_sqlalchemy.base import GaussDBDialect


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Connection:
    def __init__(self, values):
        self.values = values

    def exec_driver_sql(self, statement):
        return _ScalarResult(self.values[statement])


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _ReflectionConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = statement
        self.params = params
        return _Rows(self.rows)


def test_dialect_identity_and_defaults():
    assert GaussDBDialect.name == "gaussdb"
    assert GaussDBDialect.default_paramstyle == "pyformat"
    assert GaussDBDialect.supports_statement_cache is True
    assert GaussDBDialect.use_native_hstore is False
    assert GaussDBDialect.postgresql_compat_version == (9, 2)


def test_normalize_gaussdb_version_keeps_integer_tuples():
    assert GaussDBDialect._normalize_gaussdb_version((5, 0, 5, 1)) == (5, 0, 5, 1)


def test_normalize_gaussdb_version_strips_non_numeric_suffixes():
    assert GaussDBDialect._normalize_gaussdb_version((5, "0.5", "505.1", "build")) == (
        5,
        0,
        505,
    )


def test_normalize_gaussdb_version_handles_empty_or_unknown_values():
    assert GaussDBDialect._normalize_gaussdb_version(None) is None
    assert GaussDBDialect._normalize_gaussdb_version(()) == ()
    assert GaussDBDialect._normalize_gaussdb_version(("GaussDB",)) == ("GaussDB",)


def test_get_server_version_info_supports_gaussdb_kernel_string():
    dialect = GaussDBDialect()
    connection = _Connection(
        {
            "select pg_catalog.version()": (
                b"gaussdb (GaussDB Kernel 507.0.0 build 1268bd4d) release"
            )
        }
    )

    assert dialect._get_server_version_info(connection) == (9, 2)
    assert dialect.gaussdb_server_version_info == (507, 0, 0)
    assert "GaussDB Kernel 507.0.0" in dialect.gaussdb_server_version_string


def test_get_server_version_info_supports_postgresql_compatible_string():
    dialect = GaussDBDialect()
    connection = _Connection({"select pg_catalog.version()": "PostgreSQL 9.2.4"})

    assert dialect._get_server_version_info(connection) == (9, 2, 4)


def test_get_server_version_info_rejects_unknown_version_format():
    dialect = GaussDBDialect()
    connection = _Connection({"select pg_catalog.version()": "unknown database"})

    try:
        dialect._get_server_version_info(connection)
    except AssertionError as exc:
        assert "Could not determine GaussDB version" in str(exc)
    else:
        raise AssertionError("expected unknown version format to fail")


def test_get_default_schema_name_decodes_bytes():
    dialect = GaussDBDialect()
    connection = _Connection({"select current_schema()": b"public"})

    assert dialect._get_default_schema_name(connection) == "public"


def test_get_columns_uses_gaussdb_compatible_reflection_query():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {
                "schema_name": b"public",
                "table_name": b"demo",
                "name": b"id",
                "format_type": b"integer",
                "not_null": True,
                "default": None,
                "comment": None,
            },
            {
                "schema_name": b"public",
                "table_name": b"demo",
                "name": b"name",
                "format_type": b"character varying(32)",
                "not_null": False,
                "default": None,
                "comment": b"display name",
            },
        ]
    )

    columns = dialect.get_columns(connection, "demo")

    assert [column["name"] for column in columns] == ["id", "name"]
    assert columns[0]["nullable"] is False
    assert columns[1]["nullable"] is True
    assert columns[1]["comment"] == "display name"
    assert connection.params == {"filter_names": ("demo",)}
    assert dict(dialect.get_multi_columns(connection, filter_names=["demo"])).get(
        (None, "demo")
    )


def test_has_table_uses_gaussdb_compatible_reflection_query():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([(1,)])

    assert dialect.has_table(connection, "demo") is True
    assert "relkind in ('r', 'p', 'f', 'v', 'm')" in connection.statement.text
    assert "ANY (ARRAY" not in connection.statement.text
    assert ":schema is null" not in connection.statement.text
    assert connection.params == {"table_name": "demo"}


def test_has_table_filters_schema_without_nullable_parameter_probe():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([])

    assert dialect.has_table(connection, "demo", schema="app") is False
    assert "n.nspname = :schema" in connection.statement.text
    assert "ANY (ARRAY" not in connection.statement.text
    assert ":schema is null" not in connection.statement.text
    assert connection.params == {"table_name": "demo", "schema": "app"}


def test_get_pk_constraint_uses_gaussdb_compatible_query():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {"name": b"demo_pkey", "column_name": b"id", "ordinality": 1},
        ]
    )

    assert dialect.get_pk_constraint(connection, "demo") == {
        "constrained_columns": ["id"],
        "name": "demo_pkey",
    }
    assert ":schema is null" not in connection.statement.text
    assert connection.params == {"table_name": "demo"}


def test_get_pk_constraint_filters_schema_without_nullable_parameter_probe():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([])

    dialect.get_pk_constraint(connection, "demo", schema="app")

    assert ":schema is null" not in connection.statement.text
    assert "n.nspname = :schema" in connection.statement.text
    assert connection.params == {"table_name": "demo", "schema": "app"}


def test_get_unique_constraints_uses_gaussdb_compatible_query():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {"name": b"uq_demo_code", "column_name": b"code", "ordinality": 1},
        ]
    )

    assert dialect.get_unique_constraints(connection, "demo") == [
        {
            "name": "uq_demo_code",
            "column_names": ["code"],
            "duplicates_index": None,
        }
    ]
    assert ":schema is null" not in connection.statement.text
    assert connection.params == {"table_name": "demo"}


def test_get_unique_constraints_filters_schema_without_nullable_parameter_probe():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([])

    dialect.get_unique_constraints(connection, "demo", schema="app")

    assert ":schema is null" not in connection.statement.text
    assert "n.nspname = :schema" in connection.statement.text
    assert connection.params == {"table_name": "demo", "schema": "app"}


def test_get_indexes_uses_gaussdb_compatible_query():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {
                "index_name": b"ix_demo_name",
                "column_name": b"name",
                "is_unique": False,
                "definition": b"CREATE INDEX ix_demo_name ON demo USING btree (name)",
                "ordinality": 1,
            },
        ]
    )

    assert dialect.get_indexes(connection, "demo") == [
        {
            "name": "ix_demo_name",
            "unique": False,
            "column_names": ["name"],
            "include_columns": [],
        }
    ]
    assert ":schema is null" not in connection.statement.text
    assert connection.params == {"table_name": "demo"}


def test_get_indexes_filters_schema_without_nullable_parameter_probe():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([])

    dialect.get_indexes(connection, "demo", schema="app")

    assert ":schema is null" not in connection.statement.text
    assert "n.nspname = :schema" in connection.statement.text
    assert connection.params == {"table_name": "demo", "schema": "app"}


def test_get_indexes_keeps_expression_indexes_without_column_names():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {
                "index_name": b"ix_demo_lower_name",
                "column_name": None,
                "is_unique": False,
                "definition": b"CREATE INDEX ix_demo_lower_name ON demo USING btree (lower((name)::text))",
                "ordinality": None,
            },
        ]
    )

    assert dialect.get_indexes(connection, "demo") == [
        {
            "name": "ix_demo_lower_name",
            "unique": False,
            "column_names": [],
            "include_columns": [],
        }
    ]


def test_m_compat_expression_index_uses_gaussdb_expression_parentheses():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    metadata = MetaData()
    table = Table("demo", metadata, Column("name", String(32)))
    index = Index("ix_demo_lower_name", func.lower(table.c.name))

    compiled = str(CreateIndex(index).compile(dialect=dialect))

    assert compiled == "CREATE INDEX ix_demo_lower_name ON demo ((lower(name)))"
