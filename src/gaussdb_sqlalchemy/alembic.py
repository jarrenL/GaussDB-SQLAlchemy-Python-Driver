"""Alembic DDL integration for the GaussDB SQLAlchemy dialect."""

from __future__ import annotations

from sqlalchemy import text


_REGISTERED = False


def register_alembic_impl() -> bool:
    """Register GaussDB with Alembic when Alembic is installed."""

    global _REGISTERED
    if _REGISTERED:
        return True

    try:
        from alembic.ddl import base
        from alembic.ddl.impl import DefaultImpl
        from alembic.ddl.postgresql import PostgresqlImpl
    except Exception:
        return False

    class GaussDBMChangeColumn(base.AlterColumn):
        def __init__(self, name, column_name, newname, type_, nullable=None, **kw):
            super().__init__(name, column_name, **kw)
            self.newname = newname
            self.type_ = type_
            self.nullable = nullable

    class GaussDBMModifyColumn(base.AlterColumn):
        def __init__(self, name, column_name, type_, nullable=None, **kw):
            super().__init__(name, column_name, **kw)
            self.type_ = type_
            self.nullable = nullable

    class GaussDBImpl(PostgresqlImpl):
        __dialect__ = "gaussdb"

        def alter_column(
            self,
            table_name,
            column_name,
            *,
            nullable=None,
            server_default=False,
            name=None,
            type_=None,
            schema=None,
            autoincrement=None,
            existing_type=None,
            existing_server_default=None,
            existing_nullable=None,
            existing_autoincrement=None,
            **kw,
        ):
            if not self._is_m_compatibility():
                if type_ is None:
                    return super().alter_column(
                        table_name,
                        column_name,
                        nullable=nullable,
                        server_default=server_default,
                        name=name,
                        schema=schema,
                        autoincrement=autoincrement,
                        existing_type=existing_type,
                        existing_server_default=existing_server_default,
                        existing_nullable=existing_nullable,
                        existing_autoincrement=existing_autoincrement,
                        **kw,
                    )
                return DefaultImpl.alter_column(
                    self,
                    table_name,
                    column_name,
                    nullable=nullable,
                    server_default=server_default,
                    name=name,
                    type_=type_,
                    schema=schema,
                    autoincrement=autoincrement,
                    existing_type=existing_type,
                    existing_server_default=existing_server_default,
                    existing_nullable=existing_nullable,
                    existing_autoincrement=existing_autoincrement,
                    **kw,
                )

            if name is not None:
                change_type = type_ or existing_type or self._reflect_column_type(
                    table_name, column_name, schema
                )
                self._exec(
                    GaussDBMChangeColumn(
                        table_name,
                        column_name,
                        name,
                        change_type,
                        nullable=nullable,
                        schema=schema,
                        existing_type=existing_type,
                        existing_server_default=existing_server_default,
                        existing_nullable=existing_nullable,
                    )
                )
                name = None
                type_ = None
                existing_type = change_type
                nullable = None

            if type_ is not None or nullable is not None:
                modify_type = type_ or existing_type or self._reflect_column_type(
                    table_name, column_name, schema
                )
                self._exec(
                    GaussDBMModifyColumn(
                        table_name,
                        column_name,
                        modify_type,
                        nullable=nullable,
                        schema=schema,
                        existing_type=existing_type,
                        existing_server_default=existing_server_default,
                        existing_nullable=existing_nullable,
                    )
                )
                existing_type = modify_type
                type_ = None
                nullable = None

            return DefaultImpl.alter_column(
                self,
                table_name,
                column_name,
                nullable=nullable,
                server_default=server_default,
                name=name,
                schema=schema,
                autoincrement=autoincrement,
                existing_type=existing_type,
                existing_server_default=existing_server_default,
                existing_nullable=existing_nullable,
                existing_autoincrement=existing_autoincrement,
                **kw,
            )

        def _is_m_compatibility(self):
            if getattr(self.dialect, "gaussdb_compatibility", None) == "M":
                return True
            if getattr(self, "as_sql", False):
                return False
            bind = getattr(self, "bind", None)
            if bind is None:
                return False
            try:
                compatibility = bind.execute(
                    text(
                        """
                        select datcompatibility::text
                        from pg_database
                        where datname = current_database()
                        """
                    )
                ).scalar()
            except Exception:
                return False
            if isinstance(compatibility, bytes):
                compatibility = compatibility.decode("utf-8")
            return compatibility == "M"

        def _reflect_column_type(self, table_name, column_name, schema):
            if self.bind is None:
                raise ValueError(
                    "existing_type is required for M compatibility column rename"
                )
            columns = self.dialect.get_columns(self.bind, table_name, schema=schema)
            for column in columns:
                if column["name"] == column_name:
                    return column["type"]
            raise ValueError(
                f"Could not reflect column '{column_name}' on table '{table_name}'"
            )

    from sqlalchemy.ext.compiler import compiles

    @compiles(GaussDBMChangeColumn, "gaussdb")
    def visit_gaussdb_m_change_column(element, compiler, **kw):
        return "%s CHANGE COLUMN %s %s %s%s" % (
            base.alter_table(compiler, element.table_name, element.schema),
            base.format_column_name(compiler, element.column_name),
            base.format_column_name(compiler, element.newname),
            base.format_type(compiler, element.type_),
            _nullable_suffix(element.nullable),
        )

    @compiles(GaussDBMModifyColumn, "gaussdb")
    def visit_gaussdb_m_modify_column(element, compiler, **kw):
        return "%s MODIFY COLUMN %s %s%s" % (
            base.alter_table(compiler, element.table_name, element.schema),
            base.format_column_name(compiler, element.column_name),
            base.format_type(compiler, element.type_),
            _nullable_suffix(element.nullable),
        )

    def _nullable_suffix(nullable):
        if nullable is None:
            return ""
        return " NULL" if nullable else " NOT NULL"

    _REGISTERED = True
    return True
