"""Pytest configuration: skip integration tests when ODBC is not available."""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests when pyodbc can't load or no GaussDB host configured."""
    import os

    # Check if pyodbc can actually import (needs unixODBC on macOS/Linux)
    pyodbc_ok = False
    try:
        import pyodbc  # noqa: F401
        pyodbc_ok = True
    except Exception:
        pyodbc_ok = False

    # Also require GAUSSDB_HOST so the tests actually have a target to connect to
    host_configured = bool(os.environ.get("GAUSSDB_HOST"))

    if pyodbc_ok and host_configured:
        return

    skip_marker = pytest.mark.skip(
        reason="integration tests require pyodbc + GAUSSDB_HOST (set env: GAUSSDB_HOST, GAUSSDB_PORT, GAUSSDB_USER, GAUSSDB_PASSWORD)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
