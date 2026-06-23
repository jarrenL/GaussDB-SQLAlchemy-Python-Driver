"""Base SQLAlchemy dialect classes for GaussDB."""

from __future__ import annotations

import re

from sqlalchemy import bindparam
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.postgresql.base import PGDDLCompiler
from sqlalchemy.dialects.postgresql.base import PGTypeCompiler
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy import schema as sa_schema
from sqlalchemy import types as sqltypes
from sqlalchemy import text
from sqlalchemy.sql import expression


class GaussDBDDLCompiler(PGDDLCompiler):
    def visit_create_index(self, create, **kw):
        if self.dialect.gaussdb_compatibility != "M":
            return super().visit_create_index(create, **kw)

        index = create.element
        self._verify_index_table(index)

        text = "CREATE "
        if index.unique:
            text += "UNIQUE "
        text += "INDEX "
        if create.if_not_exists:
            text += "IF NOT EXISTS "
        text += "%s ON %s " % (
            self._prepared_index_name(index, include_schema=False),
            self.preparer.format_table(index.table),
        )

        expressions = []
        for expr in index.expressions:
            compiled = self.sql_compiler.process(
                (
                    expr.self_group()
                    if not isinstance(expr, expression.ColumnClause)
                    else expr
                ),
                include_table=False,
                literal_binds=True,
            )
            if not isinstance(expr, expression.ColumnClause):
                compiled = f"({compiled})"
            expressions.append(compiled)

        text += "(%s)" % ", ".join(expressions)
        return text

    def get_column_specification(self, column, **kwargs):
        if self.dialect.gaussdb_compatibility != "M":
            return super().get_column_specification(column, **kwargs)

        colspec = self.preparer.format_column(column)
        impl_type = column.type.dialect_impl(self.dialect)
        if isinstance(impl_type, sqltypes.TypeDecorator):
            impl_type = impl_type.impl

        has_identity = (
            column.identity is not None
            and self.dialect.supports_identity_columns
        )

        use_serial = (
            column.primary_key
            and column is column.table._autoincrement_column
            and (
                self.dialect.supports_smallserial
                or not isinstance(impl_type, sqltypes.SmallInteger)
            )
            and not has_identity
            and (
                column.default is None
                or (
                    isinstance(column.default, sa_schema.Sequence)
                    and column.default.optional
                )
            )
        )

        if use_serial:
            colspec += " " + self.dialect.type_compiler_instance.process(
                column.type,
                type_expression=column,
                identifier_preparer=self.preparer,
            )
        else:
            colspec += " " + self.dialect.type_compiler_instance.process(
                column.type,
                type_expression=column,
                identifier_preparer=self.preparer,
            )
            default = self.get_column_default_string(column)
            if default is not None:
                colspec += " DEFAULT " + default

        if column.computed is not None:
            colspec += " " + self.process(column.computed)
        if has_identity:
            colspec += " " + self.process(column.identity)

        if not column.nullable and not has_identity:
            colspec += " NOT NULL"
        elif column.nullable and has_identity:
            colspec += " NULL"
        return colspec


class GaussDBTypeCompiler(PGTypeCompiler):
    def visit_TIMESTAMP(self, type_, **kw):
        if self.dialect.gaussdb_compatibility == "M":
            if getattr(type_, "precision", None) is not None:
                return f"TIMESTAMP({type_.precision})"
            return "TIMESTAMP"
        return super().visit_TIMESTAMP(type_, **kw)

    def visit_large_binary(self, type_, **kw):
        if self.dialect.gaussdb_compatibility == "M":
            return "BLOB"
        return super().visit_large_binary(type_, **kw)


class GaussDBDialect(PGDialect):
    """PostgreSQL-compatible SQLAlchemy dialect for GaussDB.

    GaussDB centralized 505.1 is close enough to PostgreSQL for SQLAlchemy's
    PostgreSQL compiler and reflection base to be useful, but this class keeps
    the dialect name distinct and avoids PostgreSQL extension assumptions.
    """

    name = "gaussdb"
    ddl_compiler = GaussDBDDLCompiler
    type_compiler = GaussDBTypeCompiler
    supports_statement_cache = True
    supports_native_enum = True
    supports_native_boolean = True
    supports_smallserial = True
    supports_sequences = True
    sequences_optional = True
    postfetch_lastrowid = False
    default_paramstyle = "pyformat"

    # HSTORE is a PostgreSQL extension and should not be assumed for a minimal
    # GaussDB 505.1 centralized install.
    use_native_hstore = False
    postgresql_compat_version = (9, 2)
    gaussdb_compatibility = None

    def initialize(self, connection):
        super().initialize(connection)
        self.server_version_info = self._normalize_gaussdb_version(
            self.server_version_info
        )
        self.gaussdb_compatibility = self._get_database_compatibility(connection)
        if self.gaussdb_compatibility == "M":
            self.supports_native_boolean = False

    def _get_server_version_info(self, connection):
        version = connection.exec_driver_sql("select pg_catalog.version()").scalar()
        version = self._decode_if_bytes(version)

        gaussdb_version = self._match_version(version, "GaussDB Kernel")
        if gaussdb_version:
            self.gaussdb_server_version_info = gaussdb_version
            self.gaussdb_server_version_string = version
            return self.postgresql_compat_version

        postgres_version = self._match_version(version, "PostgreSQL|EnterpriseDB")
        if not postgres_version:
            raise AssertionError(
                "Could not determine GaussDB version from string '%s'" % version
            )
        return postgres_version

    def _get_default_schema_name(self, connection):
        schema_name = connection.exec_driver_sql("select current_schema()").scalar()
        return self._decode_if_bytes(schema_name)

    def _get_database_compatibility(self, connection):
        try:
            compatibility = connection.exec_driver_sql(
                """
                select datcompatibility
                from pg_database
                where datname = current_database()
                """
            ).scalar()
        except Exception:
            return None
        return self._decode_if_bytes(compatibility)

    def has_table(self, connection, table_name, schema=None, **kw):
        conditions = [
            "c.relname = :table_name",
            "c.relkind in ('r', 'p', 'f', 'v', 'm')",
        ]
        params = {"table_name": table_name}
        if schema is not None:
            conditions.append("n.nspname = :schema")
            params["schema"] = schema
        else:
            conditions.append("pg_catalog.pg_table_is_visible(c.oid)")
            conditions.append("n.nspname != 'pg_catalog'")

        query = text(
            """
            select 1
            from pg_catalog.pg_class c
            join pg_catalog.pg_namespace n on n.oid = c.relnamespace
            where
            """
            + " and ".join(conditions)
            + """
            limit 1
            """
        )
        return connection.execute(query, params).first() is not None

    def get_columns(self, connection, table_name, schema=None, **kw):
        columns = dict(
            self.get_multi_columns(
                connection,
                schema=schema,
                filter_names=[table_name],
                scope=None,
                kind=None,
                **kw,
            )
        )
        key = (schema, table_name)
        if key not in columns:
            raise NoSuchTableError(table_name)
        return columns[key]

    def get_multi_columns(
        self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw
    ):
        filter_names = tuple(filter_names or ())
        conditions = [
            "a.attnum > 0",
            "not a.attisdropped",
            "c.relkind in ('r', 'p', 'f', 'v', 'm')",
            "n.nspname != 'pg_catalog'",
        ]
        params = {}

        if schema:
            conditions.append("n.nspname = :schema")
            params["schema"] = schema
        else:
            conditions.append("pg_catalog.pg_table_is_visible(c.oid)")

        if filter_names:
            conditions.append("c.relname in :filter_names")
            params["filter_names"] = filter_names

        query = text(
            """
            select
                n.nspname as schema_name,
                c.relname as table_name,
                a.attname as name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) as format_type,
                a.attnotnull as not_null,
                pg_catalog.pg_get_expr(d.adbin, d.adrelid) as "default",
                pg_catalog.col_description(a.attrelid, a.attnum) as comment
            from pg_catalog.pg_class c
            join pg_catalog.pg_namespace n on n.oid = c.relnamespace
            join pg_catalog.pg_attribute a on a.attrelid = c.oid
            left join pg_catalog.pg_attrdef d
                on d.adrelid = a.attrelid and d.adnum = a.attnum
            where
            """
            + " and ".join(conditions)
            + """
            order by c.relname, a.attnum
            """
        )
        if filter_names:
            query = query.bindparams(bindparam("filter_names", expanding=True))

        reflected = {}
        rows = connection.execute(query, params).mappings()
        for row in rows:
            table_name = self._decode_if_bytes(row["table_name"])
            schema_name = self._decode_if_bytes(row["schema_name"])
            key = (schema_name if schema else None, table_name)
            column_name = self._decode_if_bytes(row["name"])
            format_type = self._decode_if_bytes(row["format_type"])
            normalized_type = format_type.lower() if format_type else format_type
            if normalized_type == "datea":
                format_type = "date"
            elif normalized_type == "varchar" or normalized_type.startswith("varchar("):
                format_type = "character varying"
            elif normalized_type == "decimal" or normalized_type.startswith("decimal("):
                format_type = "numeric"
            elif normalized_type == "tinyint" or normalized_type.startswith("tinyint("):
                format_type = "smallint"
            elif normalized_type in {"blob", "longblob"} or normalized_type.startswith(
                ("varbinary", "binary")
            ):
                format_type = "bytea"
            default = self._decode_if_bytes(row["default"])
            comment = self._decode_if_bytes(row["comment"])
            reflected.setdefault(key, []).append(
                {
                    "name": column_name,
                    "type": self._reflect_type(
                        format_type,
                        {},
                        {},
                        type_description=f"column '{column_name}'",
                        collation=None,
                    ),
                    "nullable": not row["not_null"],
                    "default": default,
                    "autoincrement": False,
                    "comment": comment,
                }
            )

        return reflected.items()

    def get_pk_constraint(self, connection, table_name, schema=None, **kw):
        schema_condition = ""
        params = {"table_name": table_name}
        if schema is not None:
            schema_condition = " and n.nspname = :schema"
            params["schema"] = schema

        query = text(
            f"""
            select
                con.conname as name,
                a.attname as column_name,
                a.attnum as ordinality
            from pg_catalog.pg_constraint con
            join pg_catalog.pg_class c on c.oid = con.conrelid
            join pg_catalog.pg_namespace n on n.oid = c.relnamespace
            join pg_catalog.pg_attribute a
                on a.attrelid = c.oid and a.attnum = any(con.conkey)
            where con.contype = 'p'
              and c.relname = :table_name
              {schema_condition}
            order by a.attnum
            """
        )
        rows = connection.execute(query, params).mappings()
        constraint_name = None
        constrained_columns = []
        for row in rows:
            constraint_name = self._decode_if_bytes(row["name"])
            constrained_columns.append(self._decode_if_bytes(row["column_name"]))
        return {"constrained_columns": constrained_columns, "name": constraint_name}

    def get_multi_pk_constraint(
        self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw
    ):
        constraints = {}
        for table_name in self._get_reflection_table_names(
            connection, schema, filter_names
        ):
            constraints[(schema, table_name)] = self.get_pk_constraint(
                connection, table_name, schema=schema, **kw
            )
        return constraints.items()

    def get_unique_constraints(self, connection, table_name, schema=None, **kw):
        schema_condition = ""
        params = {"table_name": table_name}
        if schema is not None:
            schema_condition = " and n.nspname = :schema"
            params["schema"] = schema

        query = text(
            f"""
            select
                con.conname as name,
                a.attname as column_name,
                a.attnum as ordinality
            from pg_catalog.pg_constraint con
            join pg_catalog.pg_class c on c.oid = con.conrelid
            join pg_catalog.pg_namespace n on n.oid = c.relnamespace
            join pg_catalog.pg_attribute a
                on a.attrelid = c.oid and a.attnum = any(con.conkey)
            where con.contype = 'u'
              and c.relname = :table_name
              {schema_condition}
            order by con.conname, a.attnum
            """
        )
        rows = connection.execute(query, params).mappings()
        constraints = {}
        for row in rows:
            name = self._decode_if_bytes(row["name"])
            constraints.setdefault(name, []).append(
                self._decode_if_bytes(row["column_name"])
            )
        return [
            {"name": name, "column_names": columns, "duplicates_index": None}
            for name, columns in constraints.items()
        ]

    def get_multi_unique_constraints(
        self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw
    ):
        constraints = {}
        for table_name in self._get_reflection_table_names(
            connection, schema, filter_names
        ):
            constraints[(schema, table_name)] = self.get_unique_constraints(
                connection, table_name, schema=schema, **kw
            )
        return constraints.items()

    def get_indexes(self, connection, table_name, schema=None, **kw):
        schema_condition = ""
        params = {"table_name": table_name}
        if schema is not None:
            schema_condition = " and n.nspname = :schema"
            params["schema"] = schema

        query = text(
            f"""
            select
                i.relname as index_name,
                x.indisunique as is_unique,
                pg_catalog.pg_get_indexdef(i.oid) as definition,
                a.attname as column_name,
                a.attnum as ordinality
            from pg_catalog.pg_class t
            join pg_catalog.pg_namespace n on n.oid = t.relnamespace
            join pg_catalog.pg_index x on x.indrelid = t.oid
            join pg_catalog.pg_class i on i.oid = x.indexrelid
            left join pg_catalog.pg_attribute a
                on a.attrelid = t.oid and a.attnum = any(x.indkey)
            where t.relname = :table_name
              {schema_condition}
              and not x.indisprimary
            order by i.relname, a.attnum
            """
        )
        rows = connection.execute(query, params).mappings()
        indexes = {}
        for row in rows:
            name = self._decode_if_bytes(row["index_name"])
            index = indexes.setdefault(
                name,
                {
                    "name": name,
                    "unique": row["is_unique"],
                    "column_names": [],
                    "include_columns": [],
                },
            )
            column_name = self._decode_if_bytes(row["column_name"])
            if column_name is not None:
                index["column_names"].append(column_name)
        return list(indexes.values())

    def get_multi_indexes(
        self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw
    ):
        indexes = {}
        for table_name in self._get_reflection_table_names(
            connection, schema, filter_names
        ):
            indexes[(schema, table_name)] = self.get_indexes(
                connection, table_name, schema=schema, **kw
            )
        return indexes.items()

    def get_table_comment(self, connection, table_name, schema=None, **kw):
        return {"text": None}

    def get_multi_table_comment(
        self, connection, schema=None, filter_names=None, scope=None, kind=None, **kw
    ):
        comments = {}
        for table_name in self._get_reflection_table_names(
            connection, schema, filter_names
        ):
            comments[(schema, table_name)] = {"text": None}
        return comments.items()

    def _get_reflection_table_names(self, connection, schema=None, filter_names=None):
        if filter_names:
            return tuple(filter_names)

        conditions = [
            "c.relkind in ('r', 'p', 'f', 'v', 'm')",
            "n.nspname != 'pg_catalog'",
        ]
        params = {}
        if schema:
            conditions.append("n.nspname = :schema")
            params["schema"] = schema
        else:
            conditions.append("pg_catalog.pg_table_is_visible(c.oid)")

        rows = connection.execute(
            text(
                """
                select c.relname
                from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                where
                """
                + " and ".join(conditions)
                + """
                order by c.relname
                """
            ),
            params,
        )
        return tuple(self._decode_if_bytes(row[0]) for row in rows)

    @staticmethod
    def _normalize_gaussdb_version(version_info):
        if not version_info:
            return version_info

        normalized = []
        for part in version_info:
            if isinstance(part, int):
                normalized.append(part)
                continue
            try:
                normalized.append(int(str(part).split(".")[0]))
            except (TypeError, ValueError):
                break
        return tuple(normalized) or version_info

    @staticmethod
    def _decode_if_bytes(value):
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    @staticmethod
    def _match_version(version, product_pattern):
        match = re.search(
            rf"(?:{product_pattern})\s+(\d+)\.?(\d+)?(?:\.(\d+))?",
            version,
            re.IGNORECASE,
        )
        if not match:
            return None
        return tuple(int(part) for part in match.group(1, 2, 3) if part is not None)
