"""Quick start: connect to GaussDB via ODBC and run a simple query."""

from sqlalchemy import create_engine, text


# Replace with your actual GaussDB connection details.
# The driver name must match what's installed in your ODBC manager.
engine = create_engine(
    "gaussdb+odbc://sqlbuilder1:huawei%40123@127.0.0.1:19995/postgres"
    "?driver=GaussDB+ODBC+Driver&sslmode=disable",
    pool_pre_ping=True,
)

with engine.begin() as conn:
    print(conn.execute(text("select 1")).scalar_one())
