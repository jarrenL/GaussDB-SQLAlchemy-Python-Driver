"""Run a live GaussDB SQLAlchemy integration probe.

The script expects GAUSSDB_TEST_URL or --url and creates temporary tables with
``gdbdrv_*`` prefixes. It is intentionally framework-free so it can run on a
database host even when pytest is not installed.
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
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


def table_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def get_compatibility(conn) -> str:
    return conn.execute(
        text(
            """
            select datcompatibility
            from pg_database
            where datname = current_database()
            """
        )
    ).scalar_one()


def run(url: str) -> tuple[str, ...]:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine(url, pool_pre_ping=True)
    results: tuple[str, ...] = ()

    table = table_name("gdbdrv_idx_ut")
    index_name = f"ix_{table}_name"
    unique_name = f"uq_{table}_code"
    metadata = MetaData()
    Table(
        table,
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
        pk = inspector.get_pk_constraint(table)
        assert_true(pk["constrained_columns"] == ["id"], f"unexpected pk: {pk}")

        uniques = inspector.get_unique_constraints(table)
        assert_true(
            any(
                constraint["name"] == unique_name
                and constraint["column_names"] == ["code"]
                for constraint in uniques
            ),
            f"unexpected unique constraints: {uniques}",
        )

        indexes = inspector.get_indexes(table)
        assert_true(
            any(
                index["name"] == index_name and index["column_names"] == ["name"]
                for index in indexes
            ),
            f"unexpected indexes: {indexes}",
        )
    finally:
        metadata.drop_all(engine)
    results += ("pk_unique_index",)

    table = table_name("gdbdrv_seq_ut")
    sequence = f"{table}_id_seq"
    with engine.begin() as conn:
        conn.execute(text(f"drop table if exists {table}"))
        compatibility = get_compatibility(conn)
        if compatibility == "M":
            conn.execute(
                text(
                    f"create table {table} ("
                    "id int primary key auto_increment, "
                    "name varchar(32))"
                )
            )
        else:
            conn.execute(text(f"drop sequence if exists {sequence}"))
            conn.execute(text(f"create sequence {sequence} start 1"))
            conn.execute(
                text(
                    f"create table {table} ("
                    f"id int primary key default nextval('{sequence}'), "
                    "name varchar(32))"
                )
            )
        conn.execute(text(f"insert into {table} (name) values (:name)"), {"name": "a"})
        conn.execute(text(f"insert into {table} (name) values (:name)"), {"name": "b"})
        rows = conn.execute(text(f"select id, name from {table} order by id")).all()
        assert_true(rows == [(1, "a"), (2, "b")], f"unexpected rows: {rows}")

        columns = {column["name"]: column for column in inspect(conn).get_columns(table)}
        if compatibility != "M":
            assert_true(
                "nextval" in columns["id"]["default"],
                f"unexpected default: {columns['id']}",
            )
        conn.execute(text(f"drop table {table}"))
        if compatibility != "M":
            conn.execute(text(f"drop sequence {sequence}"))
    results += ("auto_increment" if compatibility == "M" else "sequence",)

    table = table_name("gdbdrv_alembic_ut")
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        operations = Operations(context)
        operations.create_table(
            table,
            Column("id", Integer, primary_key=True),
            Column("name", String(32), nullable=False),
        )
        operations.add_column(table, Column("remark", String(64)))
        conn.execute(
            text(
                f"insert into {table} (id, name, remark) "
                "values (:id, :name, :remark)"
            ),
            {"id": 1, "name": "created", "remark": "via alembic"},
        )
        row = conn.execute(
            text(f"select id, name, remark from {table} where id=:id"),
            {"id": 1},
        ).one()
        assert_true(
            row == (1, "created", "via alembic"),
            f"unexpected alembic row: {row}",
        )
        operations.drop_table(table)
    results += ("alembic",)

    table = table_name("gdbdrv_types_ut")
    metadata = MetaData()
    typed_table = Table(
        table,
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
                typed_table.insert().values(
                    id=1,
                    amount=Decimal("12345.67"),
                    created_at=expected_created_at,
                    business_date=expected_date,
                    enabled=True,
                    description="GaussDB text roundtrip",
                    payload=expected_payload,
                )
            )
            row = conn.execute(select(typed_table).where(typed_table.c.id == 1)).one()
        assert_true(row.amount == Decimal("12345.67"), f"bad numeric: {row.amount}")
        assert_true(row.created_at == expected_created_at, f"bad timestamp: {row.created_at}")
        assert_true(row.business_date == expected_date, f"bad date: {row.business_date}")
        assert_true(row.enabled is True, f"bad boolean: {row.enabled}")
        assert_true(row.description == "GaussDB text roundtrip", f"bad text: {row.description}")
        assert_true(bytes(row.payload) == expected_payload, f"bad bytea: {row.payload}")
        columns = {column["name"]: column for column in inspect(engine).get_columns(table)}
        assert_true("payload" in columns, f"missing reflected columns: {columns}")
    finally:
        metadata.drop_all(engine)
    results += ("data_types",)

    table = table_name("gdbdrv_autogen_ut")
    metadata = MetaData()
    Table(
        table,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
        UniqueConstraint("name", name=f"uq_{table}_name"),
    )
    try:
        metadata.create_all(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_name": lambda name, type_, parent_names: (
                        type_ != "table" or name == table
                    )
                },
            )
            diffs = compare_metadata(context, metadata)
        assert_true(diffs == [], f"unexpected autogenerate diffs: {diffs}")
    finally:
        metadata.drop_all(engine)
    results += ("alembic_autogenerate",)

    table = table_name("gdbdrv_adv_ut")
    view = table_name("gdbdrv_view_ut")
    complex_index = f"ix_{table}_code_name"
    expression_index = f"ix_{table}_lower_name"
    with engine.begin() as conn:
        compatibility = get_compatibility(conn)
        conn.execute(text(f"drop view if exists {view}"))
        conn.execute(text(f"drop table if exists {table}"))
        conn.execute(
            text(
                f"create table {table} ("
                "id int primary key, code varchar(32), name varchar(32))"
            )
        )
        conn.execute(text(f"create index {complex_index} on {table} (code, name)"))
        probe_table = Table(
            table,
            MetaData(),
            Column("id", Integer),
            Column("code", String(32)),
            Column("name", String(32)),
        )
        Index(expression_index, func.lower(probe_table.c.name)).create(conn)
        conn.execute(
            text(
                f"create view {view} as "
                f"select id, code, name from {table} where id > 0"
            )
        )
    try:
        inspector = inspect(engine)
        indexes = inspector.get_indexes(table)
        assert_true(
            any(
                index["name"] == complex_index
                and index["column_names"] == ["code", "name"]
                for index in indexes
            ),
            f"missing complex index reflection: {indexes}",
        )
        assert_true(
            any(index["name"] == expression_index for index in indexes),
            f"missing expression index reflection: {indexes}",
        )
        view_columns = inspector.get_columns(view)
        assert_true(
            [column["name"] for column in view_columns] == ["id", "code", "name"],
            f"unexpected view columns: {view_columns}",
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop view if exists {view}"))
            conn.execute(text(f"drop table if exists {table}"))
    results += ("advanced_reflection",)

    table = table_name("gdbdrv_part_ut")
    with engine.connect() as conn:
        conn.execute(text(f"drop table if exists {table}"))
        try:
            conn.execute(
                text(
                    f"create table {table} (id int primary key, name varchar(32)) "
                    "partition by range (id) ("
                    "partition p_lt_100 values less than (100), "
                    "partition p_max values less than (maxvalue))"
                )
            )
        except Exception:
            conn.rollback()
            results += ("partition_reflection_skipped",)
        else:
            conn.commit()
            try:
                columns = inspect(conn).get_columns(table)
                assert_true(
                    [column["name"] for column in columns] == ["id", "name"],
                    f"unexpected partition columns: {columns}",
                )
                results += ("partition_reflection",)
            finally:
                conn.rollback()
                conn.execute(text(f"drop table if exists {table}"))
                conn.commit()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live GaussDB SQLAlchemy integration probe. "
            "Use a gaussdb+odbc:// URL via --url or GAUSSDB_TEST_URL."
        )
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GAUSSDB_TEST_URL"),
        help=(
            "SQLAlchemy URL in ODBC format, e.g. "
            "gaussdb+odbc://user:password@host:port/dbname"
            "?driver=GaussDB+ODBC+Driver&sslmode=disable"
        ),
    )
    args = parser.parse_args()
    if not args.url:
        parser.error("--url or GAUSSDB_TEST_URL is required")

    results = run(args.url)
    print("integration probe ok:", ",".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
