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

    target = "gaussdb_sqlalchemy.jdbc:GaussDBDialect_jdbc"
    assert entry_points["gaussdb"] == target
    assert entry_points["gaussdb.jdbc"] == target
    assert "gaussdb.gaussdb" not in entry_points


def test_readme_is_chinese_project_documentation():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "# GaussDB SQLAlchemy Python 驱动" in readme
    assert "轻量化集中式 505.1" in readme
    assert "gaussdb+jdbc://" in readme
