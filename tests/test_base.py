from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import Boolean
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import func
from sqlalchemy.schema import CreateIndex
from sqlalchemy.schema import CreateTable

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
        return self

    def __iter__(self):
        return iter(self.rows)

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


class _Cursor:
    def __init__(self, statements, row=None):
        self.statements = statements
        self.row = row
        self.closed = False

    def execute(self, statement):
        self.statements.append(statement)

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class _DbapiConnection:
    def __init__(self, row=None):
        self.statements = []
        self.row = row
        self.cursors = []

    def cursor(self):
        cursor = _Cursor(self.statements, self.row)
        self.cursors.append(cursor)
        return cursor


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
            "select pg_catalog.version()::text": (
                b"gaussdb (GaussDB Kernel 507.0.0 build 1268bd4d) release"
            )
        }
    )

    assert dialect._get_server_version_info(connection) == (9, 2)
    assert dialect.gaussdb_server_version_info == (507, 0, 0)
    assert "GaussDB Kernel 507.0.0" in dialect.gaussdb_server_version_string


def test_get_server_version_info_supports_postgresql_compatible_string():
    dialect = GaussDBDialect()
    connection = _Connection({"select pg_catalog.version()::text": "PostgreSQL 9.2.4"})

    assert dialect._get_server_version_info(connection) == (9, 2, 4)


def test_get_server_version_info_rejects_unknown_version_format():
    dialect = GaussDBDialect()
    connection = _Connection({"select pg_catalog.version()::text": "unknown database"})

    try:
        dialect._get_server_version_info(connection)
    except AssertionError as exc:
        assert "Could not determine GaussDB version" in str(exc)
    else:
        raise AssertionError("expected unknown version format to fail")


def test_get_default_schema_name_decodes_bytes():
    dialect = GaussDBDialect()
    connection = _Connection({"show search_path": b"public"})

    assert dialect._get_default_schema_name(connection) == "public"


def test_m_compat_disables_returning_and_native_boolean():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"

    dialect._apply_compatibility_features()

    assert dialect.supports_native_boolean is False
    assert dialect.insert_returning is False
    assert dialect.update_returning is False
    assert dialect.delete_returning is False
    assert dialect.insert_executemany_returning is False
    assert dialect.preexecute_autoincrement_sequences is False
    assert dialect.insert_null_pk_still_autoincrements is True


def test_m_compat_isolation_level_uses_mysql_style_session_syntax():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    connection = _DbapiConnection()

    dialect.set_isolation_level(connection, "READ COMMITTED")

    assert connection.statements == [
        "COMMIT",
        "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "COMMIT",
    ]


def test_non_m_compat_isolation_level_keeps_postgresql_session_syntax():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "A"
    connection = _DbapiConnection()

    dialect.set_isolation_level(connection, "READ COMMITTED")

    assert connection.statements == [
        "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "COMMIT",
    ]


def test_isolation_level_detects_m_compatibility_from_raw_connection():
    dialect = GaussDBDialect()
    connection = _DbapiConnection(row=(b"M",))

    dialect.set_isolation_level(connection, "READ COMMITTED")

    assert connection.statements[0].strip().startswith("select datcompatibility")
    assert connection.statements[1:] == [
        "COMMIT",
        "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
        "COMMIT",
    ]


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
    assert columns[1]["type"].length == 32
    assert columns[1]["comment"] == "display name"
    assert connection.params == {"filter_names": ("demo",)}
    assert dict(dialect.get_multi_columns(connection, filter_names=["demo"])).get(
        (None, "demo")
    )


def test_get_columns_preserves_numeric_precision_and_detects_autoincrement():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection(
        [
            {
                "schema_name": b"public",
                "table_name": b"demo",
                "name": b"id",
                "format_type": b"integer",
                "not_null": True,
                "default": b"nextval('demo_id_seq'::regclass)",
                "comment": None,
            },
            {
                "schema_name": b"public",
                "table_name": b"demo",
                "name": b"amount",
                "format_type": b"decimal(12,2)",
                "not_null": False,
                "default": None,
                "comment": None,
            },
        ]
    )

    columns = dialect.get_columns(connection, "demo")

    assert columns[0]["autoincrement"] is True
    assert columns[1]["type"].precision == 12
    assert columns[1]["type"].scale == 2


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


def test_get_table_comment_reflects_database_comment():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([{"comment": b"test comment"}])

    assert dialect.get_table_comment(connection, "demo") == {"text": "test comment"}
    assert "obj_description" in connection.statement.text
    assert connection.params == {"table_name": "demo"}


def test_get_table_comment_filters_schema():
    dialect = GaussDBDialect()
    connection = _ReflectionConnection([{"comment": None}])

    assert dialect.get_table_comment(connection, "demo", schema="app") == {"text": None}
    assert "n.nspname = :schema" in connection.statement.text
    assert connection.params == {"table_name": "demo", "schema": "app"}


def test_m_compat_expression_index_uses_gaussdb_expression_parentheses():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    metadata = MetaData()
    table = Table("demo", metadata, Column("name", String(32)))
    index = Index("ix_demo_lower_name", func.lower(table.c.name))

    compiled = str(CreateIndex(index).compile(dialect=dialect))

    assert compiled == "CREATE INDEX ix_demo_lower_name ON demo ((lower(name)))"


def test_m_compat_uses_backtick_for_quoted_identifiers():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    metadata = MetaData()
    table = Table("demo", metadata, Column("select", String(32)))

    compiled = str(CreateTable(table).compile(dialect=dialect))

    assert "`select`" in compiled
    assert '"select"' not in compiled


def test_m_compat_boolean_ddl_uses_smallint():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    metadata = MetaData()
    table = Table("demo", metadata, Column("flag", Boolean))

    compiled = str(CreateTable(table).compile(dialect=dialect))

    assert "flag SMALLINT" in compiled
    assert "BOOLEAN" not in compiled


def test_m_compat_integer_primary_key_uses_auto_increment():
    dialect = GaussDBDialect()
    dialect.gaussdb_compatibility = "M"
    metadata = MetaData()
    table = Table("demo", metadata, Column("id", Integer, primary_key=True))

    compiled = str(CreateTable(table).compile(dialect=dialect))

    assert "id INTEGER NOT NULL AUTO_INCREMENT" in compiled
    assert "SERIAL" not in compiled
