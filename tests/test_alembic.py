import pytest
from sqlalchemy import Integer
from sqlalchemy import String

from gaussdb_sqlalchemy.alembic import register_alembic_impl
from gaussdb_sqlalchemy.odbc import GaussDBDialect_odbc


def test_register_alembic_impl_when_alembic_is_installed():
    pytest.importorskip("alembic")
    from alembic.ddl.impl import _impls

    assert register_alembic_impl() is True
    registered_impl = _impls["gaussdb"]
    assert register_alembic_impl() is True
    assert _impls["gaussdb"] is registered_impl
    assert _impls["gaussdb"].__dialect__ == "gaussdb"


def test_m_compat_alembic_rename_column_uses_change_column():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "M"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column(
        "demo",
        "old_name",
        new_column_name="new_name",
        existing_type=String(32),
    )

    assert output.getvalue().strip() == (
        "ALTER TABLE demo CHANGE COLUMN old_name new_name VARCHAR(32);"
    )


def test_non_m_alembic_rename_column_keeps_postgresql_style():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "A"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column(
        "demo",
        "old_name",
        new_column_name="new_name",
        existing_type=String(32),
    )

    assert output.getvalue().strip() == "ALTER TABLE demo RENAME old_name TO new_name;"


def test_alembic_type_change_uses_sqlalchemy20_compatible_generic_sql():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "A"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column("demo", "value", type_=String(64), existing_type=Integer())

    assert output.getvalue().strip() == "ALTER TABLE demo ALTER COLUMN value TYPE VARCHAR(64);"


def test_m_alembic_type_change_uses_modify_column():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "M"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column("demo", "value", type_=String(64), existing_type=String(16))

    assert output.getvalue().strip() == "ALTER TABLE demo MODIFY COLUMN value VARCHAR(64);"


def test_m_alembic_nullable_true_uses_modify_column_null():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "M"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column("demo", "value", nullable=True, existing_type=String(16))

    assert output.getvalue().strip() == "ALTER TABLE demo MODIFY COLUMN value VARCHAR(16) NULL;"


def test_m_alembic_nullable_false_uses_modify_column_not_null():
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from io import StringIO

    register_alembic_impl()
    output = StringIO()
    dialect = GaussDBDialect_odbc()
    dialect.gaussdb_compatibility = "M"
    context = MigrationContext.configure(
        dialect=dialect,
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)

    operations.alter_column("demo", "value", nullable=False, existing_type=String(16))

    assert output.getvalue().strip() == (
        "ALTER TABLE demo MODIFY COLUMN value VARCHAR(16) NOT NULL;"
    )
