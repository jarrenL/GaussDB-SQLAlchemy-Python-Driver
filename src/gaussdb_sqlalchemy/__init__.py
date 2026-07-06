"""SQLAlchemy support for Huawei GaussDB via ODBC."""

from .alembic import register_alembic_impl
from .odbc import GaussDBDialect_odbc

register_alembic_impl()

__all__ = ["GaussDBDialect_odbc"]
__version__ = "0.2.0"
