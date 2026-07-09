"""Centralized test configuration via environment variables.

Copy tests/.env.example to .env or export the variables before running tests.
Defaults match the original hardcoded values for backwards compatibility.
"""
import os
from urllib.parse import quote_plus

GAUSSDB_HOST = os.environ.get("GAUSSDB_HOST", "121.37.186.131")
GAUSSDB_PORT = os.environ.get("GAUSSDB_PORT", "19995")
GAUSSDB_USER = os.environ.get("GAUSSDB_USER", "sqlbuilder1")
GAUSSDB_PASSWORD = os.environ.get("GAUSSDB_PASSWORD", "huawei@123")

_pwd = quote_plus(GAUSSDB_PASSWORD)

# ODBC connection base
ODBC_BASE = f"gaussdb+odbc://{GAUSSDB_USER}:{_pwd}@{GAUSSDB_HOST}:{GAUSSDB_PORT}"

ODBC_URLS = {
    "A": f"{ODBC_BASE}/postgres?sslmode=disable",
    "B": f"{ODBC_BASE}/gdbdrv_b_compat?sslmode=disable",
    "M": f"{ODBC_BASE}/testm?sslmode=disable",
}

# JDBC connection base (used by _local/manual_tests)
JDBC_BASE = f"gaussdb+jdbc://{GAUSSDB_USER}:{_pwd}@{GAUSSDB_HOST}:{GAUSSDB_PORT}"

JDBC_URLS = {
    "A": f"{JDBC_BASE}/postgres?sslmode=disable",
    "B": f"{JDBC_BASE}/gdbdrv_b_compat?sslmode=disable",
    "M": f"{JDBC_BASE}/testm?sslmode=disable",
}
