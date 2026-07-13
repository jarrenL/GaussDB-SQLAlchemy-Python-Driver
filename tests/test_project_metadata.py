from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_sqlalchemy_entry_points():
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    entry_points = pyproject["project"]["entry-points"]["sqlalchemy.dialects"]

    target = "gaussdb_sqlalchemy.odbc:GaussDBDialect_odbc"
    assert entry_points["gaussdb"] == target
    assert entry_points["gaussdb.odbc"] == target
    assert "gaussdb.jdbc" not in entry_points


def test_readme_documents_odbc_connection():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "GaussDB SQLAlchemy Python" in readme
    assert "ODBC" in readme
    assert "gaussdb+odbc://" in readme or "gaussdb://" in readme
    assert "pyodbc" in readme


def test_pyproject_dependencies_replaced_jdbc_with_odbc():
    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    deps = pyproject["project"]["dependencies"]
    dep_str = " ".join(deps)
    assert "pyodbc" in dep_str
    assert "JayDeBeApi" not in dep_str
    assert "JPype1" not in dep_str


def test_no_jdbc_artifacts_remain():
    src = PROJECT_ROOT / "src" / "gaussdb_sqlalchemy"
    assert not (src / "jdbc.py").exists()
    assert not (src / "jdbc_dbapi.py").exists()
    assert not (src / "gaussdbjdbc.jar").exists()
    assert (src / "odbc.py").exists()
    assert (src / "odbc_dbapi.py").exists()
