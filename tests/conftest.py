"""Pytest configuration: skip integration tests when ODBC is not available."""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests when pyodbc can't load."""
    # Check if pyodbc can actually import (needs unixODBC on macOS/Linux)
    pyodbc_ok = False
    try:
        import pyodbc  # noqa: F401
        pyodbc_ok = True
    except Exception:
        pyodbc_ok = False

    if pyodbc_ok:
        return

    skip_marker = pytest.mark.skip(
        reason="pyodbc not available (install unixODBC + GaussDB ODBC driver to run)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)
