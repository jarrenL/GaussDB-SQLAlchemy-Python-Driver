"""Probe PostgreSQL/Oracle/MySQL-style SQL against the configured GaussDB URL."""

from __future__ import annotations

import argparse
import os
import uuid

from sqlalchemy import create_engine
from sqlalchemy import text


def _checks():
    return [
        ("version", "select version()"),
        ("current database", "select current_database()"),
        (
            "compatibility column probe",
            "select datname, datcompatibility from pg_database "
            "where datname = current_database()",
        ),
        ("pg cast", "select '42'::int as value"),
        ("pg now", "select now() is not null as ok"),
        ("pg limit", "select generate_series(1,3) as n limit 2"),
        ("oracle dual", "select 1 from dual"),
        ("oracle nvl", "select nvl(null, 'fallback') as value"),
        ("oracle sysdate", "select sysdate from dual"),
        ("oracle rownum", "select rownum from pg_class limit 1"),
        ("mysql backtick alias", "select 1 as `value`"),
        ("mysql ifnull", "select ifnull(null, 'fallback') as value"),
        ("mysql concat function", "select concat('a', 'b') as value"),
        ("mysql current_timestamp parens", "select current_timestamp()"),
    ]


def _run_sql(conn, sql: str):
    return conn.execute(text(sql)).fetchmany(3)


def run(url: str) -> list[tuple[str, str, str]]:
    engine = create_engine(url, pool_pre_ping=True)
    results: list[tuple[str, str, str]] = []

    with engine.connect() as conn:
        for name, sql in _checks():
            try:
                rows = _run_sql(conn, sql)
                results.append((name, "PASS", repr(rows)))
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                results.append(
                    (name, "FAIL", f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
                )

    suffix = uuid.uuid4().hex[:10]
    ddl_checks = [
        (
            "pg serial table",
            f"gdbdrv_syntax_pg_{suffix}",
            [
                "create table {table} (id serial primary key, name varchar(20))",
                "insert into {table} (name) values ('ok')",
                "select id, name from {table}",
            ],
        ),
        (
            "mysql auto_increment table",
            f"gdbdrv_syntax_my_{suffix}",
            [
                "create table {table} "
                "(id int auto_increment primary key, name varchar(20))",
                "insert into {table} (name) values ('ok')",
                "select id, name from {table}",
            ],
        ),
    ]

    for name, table, statements in ddl_checks:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"drop table if exists {table}"))
                last = None
                for statement in statements:
                    sql = statement.format(table=table)
                    if sql.startswith("select"):
                        last = conn.execute(text(sql)).fetchall()
                    else:
                        conn.execute(text(sql))
                conn.execute(text(f"drop table {table}"))
            results.append((name, "PASS", repr(last)))
        except Exception as exc:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"drop table if exists {table}"))
            except Exception:
                pass
            results.append(
                (name, "FAIL", f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
            )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe PostgreSQL/Oracle/MySQL-style SQL against the configured "
            "GaussDB URL. Use a gaussdb+odbc:// URL via --url or "
            "GAUSSDB_TEST_URL."
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

    for name, status, detail in run(args.url):
        print(f"{status}\t{name}\t{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
