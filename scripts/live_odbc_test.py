#!/usr/bin/env python3
"""Live GaussDB ODBC integration test via SQLAlchemy."""

from sqlalchemy import create_engine, text

import os
import sys
from urllib.parse import quote_plus

sys.path.insert(0, "src")

_HOST = os.environ.get("GAUSSDB_HOST", "121.37.186.131")
_PORT = os.environ.get("GAUSSDB_PORT", "19995")
_USER = os.environ.get("GAUSSDB_USER", "sqlbuilder1")
_PASS = quote_plus(os.environ.get("GAUSSDB_PASSWORD", "huawei@123"))

URL = (
    f"gaussdb+odbc://{_USER}:{_PASS}@{_HOST}:{_PORT}/postgres"
    f"?driver=PostgreSQL&sslmode=disable"
)

def main():
    engine = create_engine(URL, pool_pre_ping=True)

    with engine.connect() as conn:
        val = conn.execute(text("select 1")).scalar_one()
        print(f"select 1: {val}")

        ver = conn.execute(text("select version()")).scalar_one()
        print(f"version: {str(ver)[:70]}")

        compat = conn.execute(text(
            "select datcompatibility::text from pg_database "
            "where datname = current_database()"
        )).scalar_one()
        print(f"compatibility: {compat}")

        sp = conn.execute(text("show search_path")).scalar_one()
        print(f"search_path: {sp}")

        iso = conn.execute(text("show transaction_isolation")).scalar_one()
        print(f"isolation: {iso}")

    # Test basic CRUD
    from sqlalchemy import Column, Integer, String, MetaData, Table
    metadata = MetaData()
    users = Table(
        "odbc_test_users", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
    )
    metadata.create_all(engine)
    try:
        with engine.begin() as conn:
            conn.execute(users.insert(), [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
            rows = conn.execute(text("select id, name from odbc_test_users order by id")).fetchall()
            print(f"CRUD: inserted 2 rows, fetched {len(rows)} rows: {rows}")
            conn.execute(text("delete from odbc_test_users"))
    finally:
        metadata.drop_all(engine)

    print("=== SQLAlchemy + ODBC 连接 GaussDB 成功 ===")

if __name__ == "__main__":
    main()
