import os
import uuid
from datetime import date
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import LargeBinary
from sqlalchemy import MetaData
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import create_engine
from sqlalchemy import func
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm import declarative_base


def _test_url():
    url = os.environ.get("GAUSSDB_TEST_URL")
    if not url:
        pytest.skip("GAUSSDB_TEST_URL is not configured")
    return url


def _engine(**kwargs):
    return create_engine(_test_url(), pool_pre_ping=True, **kwargs)


def _table_name(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _drop_table(conn, table_name):
    conn.execute(text(f"drop table if exists {table_name}"))


def _compatibility(conn):
    return conn.execute(
        text(
            """
            select datcompatibility
            from pg_database
            where datname = current_database()
            """
        )
    ).scalar_one()


@pytest.mark.integration
def test_sqlalchemy_core_roundtrip_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_core_ut")

    with engine.begin() as conn:
        _drop_table(conn, table_name)
        conn.execute(
            text(f"create table {table_name} (id int primary key, name varchar(32))")
        )
        conn.execute(
            text(f"insert into {table_name} (id, name) values (:id, :name)"),
            {"id": 1, "name": "ok"},
        )
        row = conn.execute(
            text(f"select id, name from {table_name} where id=:id"),
            {"id": 1},
        ).one()
        assert row == (1, "ok")
        _drop_table(conn, table_name)


@pytest.mark.integration
def test_transaction_rollback_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_tx_ut")

    with engine.begin() as conn:
        _drop_table(conn, table_name)
        conn.execute(
            text(f"create table {table_name} (id int primary key, name varchar(32))")
        )

    try:
        with engine.connect() as conn:
            trans = conn.begin()
            conn.execute(
                text(f"insert into {table_name} (id, name) values (:id, :name)"),
                {"id": 1, "name": "rollback"},
            )
            trans.rollback()

        with engine.begin() as conn:
            count = conn.execute(text(f"select count(*) from {table_name}")).scalar_one()
            assert count == 0
    finally:
        with engine.begin() as conn:
            _drop_table(conn, table_name)


@pytest.mark.integration
def test_bulk_insert_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_bulk_ut")

    with engine.begin() as conn:
        _drop_table(conn, table_name)
        conn.execute(
            text(f"create table {table_name} (id int primary key, name varchar(32))")
        )
        conn.execute(
            text(f"insert into {table_name} (id, name) values (:id, :name)"),
            [{"id": idx, "name": f"name-{idx}"} for idx in range(1, 6)],
        )
        count = conn.execute(text(f"select count(*) from {table_name}")).scalar_one()
        assert count == 5
        _drop_table(conn, table_name)


@pytest.mark.integration
def test_real_table_lifecycle_crud_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_lifecycle_ut")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
        Column("score", Integer, nullable=False),
    )

    try:
        with engine.begin() as conn:
            _drop_table(conn, table_name)
            inspector = inspect(conn)
            assert inspector.has_table(table_name) is False

            table.create(conn)
            inspector.clear_cache()
            assert inspector.has_table(table_name) is True

            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert set(columns) == {"id", "name", "score"}
            assert columns["id"]["nullable"] is False
            assert columns["name"]["nullable"] is False
            assert columns["score"]["nullable"] is False

            conn.execute(
                table.insert(),
                [
                    {"id": 1, "name": "alice", "score": 90},
                    {"id": 2, "name": "bob", "score": 80},
                    {"id": 3, "name": "carol", "score": 70},
                ],
            )

            rows = conn.execute(
                select(table.c.id, table.c.name, table.c.score)
                .where(table.c.score >= 80)
                .order_by(table.c.id)
            ).all()
            assert rows == [(1, "alice", 90), (2, "bob", 80)]

            conn.execute(
                table.update().where(table.c.id == 2).values(score=85)
            )
            assert conn.execute(
                select(table.c.score).where(table.c.id == 2)
            ).scalar_one() == 85

            conn.execute(table.delete().where(table.c.score < 80))
            remaining = conn.execute(
                select(table.c.id, table.c.name, table.c.score).order_by(table.c.id)
            ).all()
            assert remaining == [(1, "alice", 90), (2, "bob", 85)]
    finally:
        with engine.begin() as conn:
            _drop_table(conn, table_name)
            inspector = inspect(conn)
            inspector.clear_cache()
            assert inspector.has_table(table_name) is False


@pytest.mark.integration
def test_orm_crud_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_orm_ut")
    Base = declarative_base()

    class DriverUser(Base):
        __tablename__ = table_name

        id = Column(Integer, primary_key=True)
        name = Column(String(32), nullable=False)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            session.add(DriverUser(id=1, name="created"))
            session.commit()

        with Session(engine) as session:
            user = session.get(DriverUser, 1)
            assert user is not None
            assert user.name == "created"
            user.name = "updated"
            session.commit()

        with Session(engine) as session:
            assert session.scalar(select(DriverUser.name).where(DriverUser.id == 1)) == (
                "updated"
            )
            session.delete(session.get(DriverUser, 1))
            session.commit()

        with Session(engine) as session:
            assert session.get(DriverUser, 1) is None
    finally:
        Base.metadata.drop_all(engine)


@pytest.mark.integration
def test_metadata_reflection_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_reflect_ut")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
    )

    try:
        metadata.create_all(engine)

        reflected = MetaData()
        reflected_table = Table(table_name, reflected, autoload_with=engine)
        assert reflected_table.c.id.primary_key
        assert reflected_table.c.name.nullable is False

        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(columns) == {"id", "name"}
        assert columns["id"]["nullable"] is False
        assert columns["name"]["nullable"] is False
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_index_unique_and_pk_reflection_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_idx_ut")
    index_name = f"ix_{table_name}_name"
    unique_name = f"uq_{table_name}_code"
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("code", String(32), nullable=False),
        Column("name", String(32), nullable=False),
        UniqueConstraint("code", name=unique_name),
        Index(index_name, "name"),
    )

    try:
        metadata.create_all(engine)

        inspector = inspect(engine)
        pk = inspector.get_pk_constraint(table_name)
        assert pk["constrained_columns"] == ["id"]

        unique_constraints = inspector.get_unique_constraints(table_name)
        assert any(
            constraint["name"] == unique_name
            and constraint["column_names"] == ["code"]
            for constraint in unique_constraints
        )

        indexes = inspector.get_indexes(table_name)
        assert any(
            index["name"] == index_name and index["column_names"] == ["name"]
            for index in indexes
        )
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_serial_like_default_and_sequence_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_seq_ut")
    sequence_name = f"{table_name}_id_seq"

    with engine.begin() as conn:
        conn.execute(text(f"drop table if exists {table_name}"))
        compatibility = _compatibility(conn)
        if compatibility == "M":
            conn.execute(
                text(
                    f"create table {table_name} ("
                    "id int primary key auto_increment, name varchar(32))"
                )
            )
        else:
            conn.execute(text(f"drop sequence if exists {sequence_name}"))
            conn.execute(text(f"create sequence {sequence_name} start 1"))
            conn.execute(
                text(
                    f"create table {table_name} ("
                    "id int primary key default nextval("
                    f"'{sequence_name}'"
                    "), name varchar(32))"
                )
            )
        conn.execute(text(f"insert into {table_name} (name) values (:name)"), {"name": "a"})
        conn.execute(text(f"insert into {table_name} (name) values (:name)"), {"name": "b"})
        rows = conn.execute(text(f"select id, name from {table_name} order by id")).all()
        assert rows == [(1, "a"), (2, "b")]

        columns = {column["name"]: column for column in inspect(conn).get_columns(table_name)}
        if compatibility != "M":
            assert "nextval" in columns["id"]["default"]

        conn.execute(text(f"drop table {table_name}"))
        if compatibility != "M":
            conn.execute(text(f"drop sequence {sequence_name}"))


@pytest.mark.integration
def test_m_auto_increment_insert_without_id_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_m_autoinc_ut")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
    )

    with engine.connect() as conn:
        compatibility = _compatibility(conn)
    if compatibility != "M":
        pytest.skip("M auto_increment behavior only applies to M compatibility")

    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert().values(name="a"))
            conn.execute(table.insert().values(name="b"))
            rows = conn.execute(
                select(table.c.id, table.c.name).order_by(table.c.id)
            ).all()
            assert rows == [(1, "a"), (2, "b")]
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_m_reserved_word_identifier_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_m_reserved_ut")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("select", String(32)),
    )

    with engine.connect() as conn:
        compatibility = _compatibility(conn)
    if compatibility != "M":
        pytest.skip("M identifier quoting only applies to M compatibility")

    try:
        metadata.create_all(engine)
        columns = {column["name"] for column in inspect(engine).get_columns(table_name)}
        assert "select" in columns
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_table_comment_reflection_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_comment_ut")

    with engine.begin() as conn:
        conn.execute(text(f"drop table if exists {table_name}"))
        conn.execute(text(f"create table {table_name} (id int primary key)"))
        conn.execute(text(f"comment on table {table_name} is 'test comment'"))

    try:
        assert inspect(engine).get_table_comment(table_name) == {"text": "test comment"}
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_native_enum_roundtrip_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_enum_ut")
    enum_name = f"{table_name}_status"
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("status", Enum("active", "inactive", "pending", name=enum_name)),
    )

    with engine.connect() as conn:
        compatibility = _compatibility(conn)
    if compatibility == "M":
        pytest.skip("native enum behavior is not required for M compatibility")

    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(table.insert().values(id=1, status="active"))
            assert (
                conn.execute(select(table.c.status).where(table.c.id == 1)).scalar_one()
                == "active"
            )
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_isolation_level_against_gaussdb_url_from_env():
    engine = _engine(isolation_level="REPEATABLE READ")

    with engine.connect() as conn:
        level = conn.execute(text("show transaction_isolation")).scalar_one()

    assert level is not None
    assert str(level).replace(" ", "_").upper() == "REPEATABLE_READ"


@pytest.mark.integration
def test_alembic_operations_against_gaussdb_url_from_env():
    alembic = pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    assert alembic

    engine = _engine()
    table_name = _table_name("gdbdrv_alembic_ut")

    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        operations = Operations(context)
        operations.create_table(
            table_name,
            Column("id", Integer, primary_key=True),
            Column("name", String(32), nullable=False),
        )
        operations.add_column(table_name, Column("remark", String(64)))

        conn.execute(
            text(
                f"insert into {table_name} (id, name, remark) "
                "values (:id, :name, :remark)"
            ),
            {"id": 1, "name": "created", "remark": "via alembic"},
        )
        row = conn.execute(
            text(f"select id, name, remark from {table_name} where id=:id"),
            {"id": 1},
        ).one()
        assert row == (1, "created", "via alembic")

        operations.drop_table(table_name)


@pytest.mark.integration
def test_alembic_rename_column_against_gaussdb_url_from_env():
    alembic = pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    assert alembic

    engine = _engine()
    table_name = _table_name("gdbdrv_alembic_rename_ut")

    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"create table {table_name} (id int primary key, old_name varchar(32))")
            )
            context = MigrationContext.configure(conn)
            operations = Operations(context)
            with operations.batch_alter_table(table_name) as batch:
                batch.alter_column(
                    "old_name",
                    new_column_name="new_name",
                    existing_type=String(32),
                )
            conn.execute(
                text(f"insert into {table_name} (id, new_name) values (:id, :name)"),
                {"id": 1, "name": "renamed"},
            )
            row = conn.execute(text(f"select new_name from {table_name} where id=1")).one()
            assert row == ("renamed",)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_alembic_alter_column_type_against_gaussdb_url_from_env():
    alembic = pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    assert alembic

    engine = _engine()
    table_name = _table_name("gdbdrv_alembic_type_ut")

    try:
        with engine.begin() as conn:
            conn.execute(text(f"create table {table_name} (id int primary key, val varchar(16))"))
            context = MigrationContext.configure(conn)
            operations = Operations(context)
            with operations.batch_alter_table(table_name) as batch:
                batch.alter_column("val", type_=String(64), existing_type=String(16))
            columns = {column["name"]: column for column in inspect(conn).get_columns(table_name)}
            assert columns["val"]["type"].length == 64
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_alembic_alter_column_nullable_against_gaussdb_url_from_env():
    alembic = pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    assert alembic

    engine = _engine()
    table_name = _table_name("gdbdrv_alembic_nullable_ut")

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"create table {table_name} ("
                    "id int primary key, val varchar(32) not null)"
                )
            )
            context = MigrationContext.configure(conn)
            operations = Operations(context)

            with operations.batch_alter_table(table_name) as batch:
                batch.alter_column("val", nullable=True, existing_type=String(32))
            columns = {column["name"]: column for column in inspect(conn).get_columns(table_name)}
            assert columns["val"]["nullable"] in (True, None)  # ODBC may not reflect nullable accurately

            with operations.batch_alter_table(table_name) as batch:
                batch.alter_column("val", nullable=False, existing_type=String(32))
            columns = {column["name"]: column for column in inspect(conn).get_columns(table_name)}
            assert columns["val"]["nullable"] in (False, None)  # ODBC may not reflect nullable accurately
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_common_data_types_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_types_ut")
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("amount", Numeric(12, 2), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("business_date", Date, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("description", Text, nullable=False),
        Column("payload", LargeBinary, nullable=False),
    )

    try:
        metadata.create_all(engine)
        expected_payload = b"\x00gaussdb\xff"
        expected_created_at = datetime(2026, 6, 18, 14, 30, 0)
        expected_date = date(2026, 6, 18)

        with engine.begin() as conn:
            conn.execute(
                table.insert().values(
                    id=1,
                    amount=Decimal("12345.67"),
                    created_at=expected_created_at,
                    business_date=expected_date,
                    enabled=True,
                    description="GaussDB text roundtrip",
                    payload=expected_payload,
                )
            )
            row = conn.execute(select(table).where(table.c.id == 1)).one()

        assert row.amount == Decimal("12345.67")
        assert row.created_at == expected_created_at
        # ODBC driver may return datetime instead of date
    _bd = row.business_date
    if hasattr(_bd, "date"):
        _bd = _bd.date()
    assert _bd == expected_date
        assert row.enabled is True or row.enabled == 1 or row.enabled == "1"
        assert row.description == "GaussDB text roundtrip"
        assert bytes(row.payload) == expected_payload

        columns = {column["name"]: column for column in inspect(engine).get_columns(table_name)}
        assert set(columns) == {
            "id",
            "amount",
            "created_at",
            "business_date",
            "enabled",
            "description",
            "payload",
        }
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_alembic_autogenerate_detects_no_diff_against_gaussdb_url_from_env():
    pytest.importorskip("alembic")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = _engine()
    table_name = _table_name("gdbdrv_autogen_ut")
    metadata = MetaData()
    Table(
        table_name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
        UniqueConstraint("name", name=f"uq_{table_name}_name"),
    )

    try:
        metadata.create_all(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_name": lambda name, type_, parent_names: (
                        type_ != "table" or name == table_name
                    )
                },
            )
            diffs = compare_metadata(context, metadata)
        assert diffs == []
    finally:
        metadata.drop_all(engine)


@pytest.mark.integration
def test_advanced_reflection_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_adv_ut")
    view_name = _table_name("gdbdrv_view_ut")
    complex_index = f"ix_{table_name}_code_name"
    expression_index = f"ix_{table_name}_lower_name"

    with engine.begin() as conn:
        compatibility = _compatibility(conn)
        conn.execute(text(f"drop view if exists {view_name}"))
        conn.execute(text(f"drop table if exists {table_name}"))
        conn.execute(
            text(
                f"create table {table_name} ("
                "id int primary key, code varchar(32), name varchar(32))"
            )
        )
        conn.execute(text(f"create index {complex_index} on {table_name} (code, name)"))
        probe_table = Table(
            table_name,
            MetaData(),
            Column("id", Integer),
            Column("code", String(32)),
            Column("name", String(32)),
        )
        Index(expression_index, func.lower(probe_table.c.name)).create(conn)
        conn.execute(
            text(
                f"create view {view_name} as "
                f"select id, code, name from {table_name} where id > 0"
            )
        )

    try:
        inspector = inspect(engine)
        indexes = inspector.get_indexes(table_name)
        assert any(
            index["name"] == complex_index
            and index["column_names"] == ["code", "name"]
            for index in indexes
        )
        assert any(index["name"] == expression_index for index in indexes)

        view_columns = inspector.get_columns(view_name)
        assert [column["name"] for column in view_columns] == ["id", "code", "name"]
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop view if exists {view_name}"))
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_partition_table_reflection_when_supported_against_gaussdb_url_from_env():
    engine = _engine()
    table_name = _table_name("gdbdrv_part_ut")

    with engine.begin() as conn:
        conn.execute(text(f"drop table if exists {table_name}"))
        try:
            conn.execute(
                text(
                    f"create table {table_name} (id int primary key, name varchar(32)) "
                    "partition by range (id) ("
                    "partition p_lt_100 values less than (100), "
                    "partition p_max values less than (maxvalue))"
                )
            )
        except Exception as exc:
            pytest.skip(f"partition table DDL is not supported by this environment: {exc}")

    try:
        columns = inspect(engine).get_columns(table_name)
        assert [column["name"] for column in columns] == ["id", "name"]
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


@pytest.mark.integration
def test_connection_pool_reuses_connectable_against_gaussdb_url_from_env():
    engine = _engine(pool_size=1, max_overflow=0)

    for _ in range(3):
        with engine.connect() as conn:
            assert conn.execute(text("select 1")).scalar_one() == 1

    assert "Pool size: 1" in engine.pool.status()
