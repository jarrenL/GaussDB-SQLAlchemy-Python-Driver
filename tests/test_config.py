"""Centralized test configuration via environment variables.

Copy tests/.env.example to .env or export the variables before running tests.

Required:
    GAUSSDB_HOST, GAUSSDB_PORT, GAUSSDB_USER, GAUSSDB_PASSWORD

Optional (with defaults):
    GAUSSDB_DRIVER   — ODBC driver name registered in Windows ODBC Manager
    GAUSSDB_DB_A     — database name for A-compat mode
    GAUSSDB_DB_B     — database name for B-compat mode
    GAUSSDB_DB_M     — database name for M-compat mode

If GAUSSDB_HOST is not set, integration tests are skipped automatically.
"""
import os
from urllib.parse import quote_plus

GAUSSDB_HOST = os.environ.get("GAUSSDB_HOST")
GAUSSDB_PORT = os.environ.get("GAUSSDB_PORT", "19995")
GAUSSDB_USER = os.environ.get("GAUSSDB_USER", "")
GAUSSDB_PASSWORD = os.environ.get("GAUSSDB_PASSWORD", "")

# ODBC driver name — auto-detect if not explicitly set
def _detect_odbc_driver():
    """Try to find a GaussDB ODBC driver from the system."""
    explicit = os.environ.get("GAUSSDB_DRIVER")
    if explicit:
        return explicit
    try:
        import pyodbc
        for name in pyodbc.drivers():
            low = name.lower()
            if "gaussdb" in low:
                return name
        # Fallback: PostgreSQL driver also works (GaussDB is PG-compatible)
        for name in pyodbc.drivers():
            if "postgresql" in name.lower() and "unicode" in name.lower():
                return name
    except Exception:
        pass
    return "GaussDB ODBC Driver"

GAUSSDB_DRIVER = _detect_odbc_driver()
_driver = quote_plus(GAUSSDB_DRIVER)

# Database names for each compatibility mode
GAUSSDB_DB_A = os.environ.get("GAUSSDB_DB_A", "postgres")
GAUSSDB_DB_B = os.environ.get("GAUSSDB_DB_B", "gdbdrv_b_compat")
GAUSSDB_DB_M = os.environ.get("GAUSSDB_DB_M", "testm")

_pwd = quote_plus(GAUSSDB_PASSWORD) if GAUSSDB_PASSWORD else ""

# ODBC connection base
ODBC_BASE = f"gaussdb+odbc://{GAUSSDB_USER}:{_pwd}@{GAUSSDB_HOST}:{GAUSSDB_PORT}"

ODBC_URLS = {
    "A": f"{ODBC_BASE}/{GAUSSDB_DB_A}?driver={_driver}&sslmode=disable",
    "B": f"{ODBC_BASE}/{GAUSSDB_DB_B}?driver={_driver}&sslmode=disable",
    "M": f"{ODBC_BASE}/{GAUSSDB_DB_M}?driver={_driver}&sslmode=disable",
}

# JDBC connection base (used by _local/manual_tests)
JDBC_BASE = f"gaussdb+jdbc://{GAUSSDB_USER}:{_pwd}@{GAUSSDB_HOST}:{GAUSSDB_PORT}"

JDBC_URLS = {
    "A": f"{JDBC_BASE}/{GAUSSDB_DB_A}?sslmode=disable",
    "B": f"{JDBC_BASE}/{GAUSSDB_DB_B}?sslmode=disable",
    "M": f"{JDBC_BASE}/{GAUSSDB_DB_M}?sslmode=disable",
}

# Single-URL convenience (for test_integration_env.py)
# If GAUSSDB_TEST_URL is set, use it directly; otherwise derive from ODBC_URLS["A"]
GAUSSDB_TEST_URL = os.environ.get("GAUSSDB_TEST_URL") or (ODBC_URLS["A"] if GAUSSDB_HOST else None)
