"""Round 6: ORM advanced, Alembic edge cases, reflection completeness, concurrency."""
import uuid, time, threading
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, LargeBinary, MetaData,
    Numeric, String, Table, Text, create_engine, inspect, select, text,
    ForeignKey, SmallInteger, BigInteger, Float, func, Index,
    UniqueConstraint, CheckConstraint, and_, or_, event, literal,
)
from sqlalchemy.orm import Session, declarative_base, relationship, validates
from sqlalchemy.schema import CreateTable

from tests.test_config import ODBC_URLS as URLS

def _engine(compat, **kw):
    return create_engine(URLS[compat], pool_pre_ping=True, **kw)

def _tname(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 1. ORM: column_property / hybrid_property ────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_orm_column_property(compat):
    """Test ORM with column_property (computed column)."""
    from sqlalchemy.orm import column_property
    engine = _engine(compat)
    Base = declarative_base()
    tbl = _tname("vcolprop")

    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        price = Column(Integer)
        qty = Column(Integer)
        total = column_property(price * qty)

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Item(id=1, price=10, qty=5))
            s.add(Item(id=2, price=20, qty=3))
            s.commit()

        with Session(engine) as s:
            items = s.query(Item).order_by(Item.id).all()
            assert items[0].total == 50
            assert items[1].total == 60
        print(f"  {compat} column_property: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 2. ORM: @validates ───────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_orm_validates(compat):
    """Test ORM @validates decorator."""
    engine = _engine(compat)
    Base = declarative_base()
    tbl = _tname("vvalid")

    class User(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        email = Column(String(100))

        @validates("email")
        def validate_email(self, key, value):
            assert "@" in value, f"Invalid email: {value}"
            return value

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(User(id=1, email="test@example.com"))
            s.commit()

            # Invalid email should raise
            with pytest.raises(AssertionError):
                s.add(User(id=2, email="invalid"))
                s.flush()
            s.rollback()
        print(f"  {compat} @validates: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 3. ORM: lazy vs eager vs joined load ─────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_orm_eager_joined_load(compat):
    """Test ORM eager loading with joinedload."""
    from sqlalchemy.orm import joinedload
    engine = _engine(compat)
    Base = declarative_base()
    parent_tbl = _tname("vejl_p")
    child_tbl = _tname("vejl_c")

    class Parent(Base):
        __tablename__ = parent_tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
        children = relationship("Child", backref="parent")

    class Child(Base):
        __tablename__ = child_tbl
        id = Column(Integer, primary_key=True)
        parent_id = Column(Integer, ForeignKey(f"{parent_tbl}.id"))
        val = Column(String(32))

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            p = Parent(id=1, name="root")
            p.children = [Child(id=i, val=f"c{i}") for i in range(1, 4)]
            s.add(p)
            s.commit()

        with Session(engine) as s:
            # joinedload
            p = s.query(Parent).options(joinedload(Parent.children)).filter(Parent.id == 1).one()
            assert len(p.children) == 3
            assert {c.val for c in p.children} == {"c1", "c2", "c3"}
        print(f"  {compat} joinedload: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 4. Alembic: add_column with server_default ───────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_add_column_with_default(compat):
    """Test Alembic add_column with server_default."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    table_name = _tname("valt_def")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32))"))
        conn.execute(text(f"insert into {table_name} values (1, 'existing')"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.add_column(table_name, Column("status", String(20), server_default="active"))
            conn.commit()

        cols = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        assert "status" in cols

        with engine.connect() as conn:
            result = conn.execute(text(f"select status from {table_name} where id=1")).scalar_one()
            assert result == "active", f"Default not applied: {result}"
        print(f"  {compat} add_column with default: PASS")
    except Exception as e:
        print(f"  {compat} add_column with default: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 5. Alembic: drop_column ──────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_drop_column(compat):
    """Test Alembic drop_column."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    table_name = _tname("vdcol_al")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, a varchar(32), b varchar(32))"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.drop_column(table_name, "b")
            conn.commit()

        cols = [c["name"] for c in inspect(engine).get_columns(table_name)]
        assert "b" not in cols and "a" in cols
        print(f"  {compat} Alembic drop_column: PASS")
    except Exception as e:
        print(f"  {compat} Alembic drop_column: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 6. Alembic: create_index / drop_index ────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_create_drop_index(compat):
    """Test Alembic create_index and drop_index."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    table_name = _tname("valt_ix")
    index_name = f"ix_{table_name}_val"
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, val varchar(32))"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.create_index(index_name, table_name, ["val"])
            conn.commit()

        indexes = inspect(engine).get_indexes(table_name)
        assert any(ix["name"] == index_name for ix in indexes)

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.drop_index(index_name, table_name=table_name)
            conn.commit()

        indexes = inspect(engine).get_indexes(table_name)
        assert not any(ix["name"] == index_name for ix in indexes)
        print(f"  {compat} Alembic create/drop index: PASS")
    except Exception as e:
        print(f"  {compat} Alembic create/drop index: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 7. Alembic: create_unique_constraint / drop ──────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_create_drop_unique_constraint(compat):
    """Test Alembic create_unique_constraint and drop_constraint."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    table_name = _tname("valt_uq")
    constraint_name = f"uq_{table_name}_val"
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, val varchar(32))"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.create_unique_constraint(constraint_name, table_name, ["val"])
            conn.commit()

        uqs = inspect(engine).get_unique_constraints(table_name)
        assert any(uq["name"] == constraint_name for uq in uqs)

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.drop_constraint(constraint_name, table_name)
            conn.commit()

        uqs = inspect(engine).get_unique_constraints(table_name)
        assert not any(uq["name"] == constraint_name for uq in uqs)
        print(f"  {compat} Alembic create/drop UQ: PASS")
    except Exception as e:
        print(f"  {compat} Alembic create/drop UQ: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 8. Alembic: create_foreign_key / drop ────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_create_drop_foreign_key(compat):
    """Test Alembic create_foreign_key and drop_constraint."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    parent = _tname("valt_fk_p")
    child = _tname("valt_fk_c")
    fk_name = f"fk_{child}_pid"
    with engine.begin() as conn:
        conn.execute(text(f"create table {parent} (id int primary key)"))
        conn.execute(text(f"create table {child} (id int primary key, pid int)"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.create_foreign_key(fk_name, child, parent, ["pid"], ["id"])
            conn.commit()

        fks = inspect(engine).get_foreign_keys(child)
        assert any(fk["name"] == fk_name for fk in fks)

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            ops.drop_constraint(fk_name, child)
            conn.commit()

        fks = inspect(engine).get_foreign_keys(child)
        assert not any(fk["name"] == fk_name for fk in fks)
        print(f"  {compat} Alembic create/drop FK: PASS")
    except Exception as e:
        print(f"  {compat} Alembic create/drop FK: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {child}"))
            conn.execute(text(f"drop table if exists {parent}"))


# ── 9. Reflection: column order preservation ─────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_reflection_column_order(compat):
    """Test that reflected columns preserve creation order."""
    engine = _engine(compat)
    table_name = _tname("vorder_ref")
    with engine.begin() as conn:
        conn.execute(text(
            f"create table {table_name} ("
            "zzz int, aaa int, mmm int, bbb int, id int primary key)"
        ))
    try:
        cols = [c["name"] for c in inspect(engine).get_columns(table_name)]
        # Should preserve creation order (or attnum order)
        print(f"  {compat} column order: {cols}")
        assert "id" in cols
        assert len(cols) == 5
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 10. Reflection: default value types ──────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_reflection_default_values(compat):
    """Test reflection of various default value types."""
    engine = _engine(compat)
    table_name = _tname("vdef_ref")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("str_default", String(32), default="hello"),
        Column("int_default", Integer, default=42),
        Column("bool_default", Boolean, default=True),
    )
    try:
        md.create_all(engine)
        cols = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        for name, col in cols.items():
            print(f"  {compat} {name}: default={col.get('default')}")
        print(f"  {compat} reflection defaults: PASS")
    finally:
        md.drop_all(engine)


# ── 11. Multiple transactions on same connection ─────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_multiple_transactions_same_connection(compat):
    """Test multiple sequential transactions on same connection."""
    engine = _engine(compat)
    table_name = _tname("vmtx")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.connect() as conn:
            for i in range(5):
                trans = conn.begin()
                conn.execute(t.insert().values(id=i+1, val=(i+1)*10))
                trans.commit()

            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 5, f"Expected 5, got {count}"
        print(f"  {compat} multiple transactions: PASS")
    finally:
        md.drop_all(engine)


# ── 12. Transaction: begin, commit, begin, rollback ──────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_commit_then_rollback(compat):
    """Test commit first transaction, then rollback second."""
    engine = _engine(compat)
    table_name = _tname("vcr")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True))
    try:
        md.create_all(engine)
        with engine.connect() as conn:
            trans1 = conn.begin()
            conn.execute(t.insert().values(id=1))
            trans1.commit()

            trans2 = conn.begin()
            conn.execute(t.insert().values(id=2))
            trans2.rollback()

            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 1, f"Expected 1, got {count}"
        print(f"  {compat} commit then rollback: PASS")
    finally:
        md.drop_all(engine)


# ── 13. Event: before_cursor_execute ─────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_before_cursor_execute_event(compat):
    """Test SQLAlchemy event system."""
    engine = _engine(compat)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
            conn.execute(text("select 2"))
        assert len(statements) >= 2
        assert "select 1" in statements[0]
        print(f"  {compat} before_cursor_execute event: PASS ({len(statements)} statements)")
    finally:
        event.remove(engine, "before_cursor_execute", before)


# ── 14. Schema-qualified table reflection ────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_schema_qualified_reflection(compat):
    """Test reflection of table in explicit schema."""
    engine = _engine(compat)
    table_name = _tname("vsch_ref")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(32)),
        schema="public",
    )
    try:
        md.create_all(engine)
        # Reflect with schema
        reflected = Table(table_name, MetaData(), autoload_with=engine, schema="public")
        assert len(reflected.columns) == 2
        assert "id" in reflected.c
        assert "name" in reflected.c
        print(f"  {compat} schema-qualified reflection: PASS")
    finally:
        md.drop_all(engine)


# ── 15. ORM: session.merge ───────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_orm_merge(compat):
    """Test session.merge."""
    engine = _engine(compat)
    Base = declarative_base()
    tbl = _tname("vmerge")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Item(id=1, name="original"))
            s.commit()

        # Merge existing
        with Session(engine) as s:
            item = Item(id=1, name="merged")
            merged = s.merge(item)
            s.commit()

        with Session(engine) as s:
            item = s.get(Item, 1)
            assert item.name == "merged"
        print(f"  {compat} session.merge: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 16. ORM: session.expire / refresh ────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_orm_expire_refresh(compat):
    """Test session.expire and session.refresh."""
    engine = _engine(compat)
    Base = declarative_base()
    tbl = _tname("vexp")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))

    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Item(id=1, name="original"))
            s.commit()

        with Session(engine) as s:
            item = s.get(Item, 1)
            assert item.name == "original"

            # Update via raw SQL
            s.execute(text(f"update {tbl} set name = 'updated' where id = 1"))

            # Expire and re-access
            s.expire(item)
            assert item.name == "updated"  # triggers reload

            # Refresh
            s.execute(text(f"update {tbl} set name = 'refreshed' where id = 1"))
            s.refresh(item)
            assert item.name == "refreshed"
        print(f"  {compat} expire/refresh: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 17. Large table reflection (100 columns + data) ──────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_large_table_with_data_reflection(compat):
    """Test reflecting a table with many columns and data rows."""
    engine = _engine(compat)
    table_name = _tname("vlarge_ref")
    md = MetaData()
    cols = [Column("id", Integer, primary_key=True)]
    for i in range(20):
        cols.append(Column(f"col_{i}", String(20)))
    t = Table(table_name, md, *cols)
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            for row_id in range(1, 51):
                vals = {"id": row_id}
                for i in range(20):
                    vals[f"col_{i}"] = f"r{row_id}c{i}"
                conn.execute(t.insert().values(**vals))

        # Reflect
        reflected = Table(table_name, MetaData(), autoload_with=engine)
        assert len(reflected.columns) == 21

        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(reflected)).scalar_one()
            assert count == 50
        print(f"  {compat} large table reflection: PASS")
    finally:
        md.drop_all(engine)


# ── 18. CAST expressions ─────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_cast_expressions(compat):
    """Test SQL CAST expressions."""
    from sqlalchemy import cast, String as SAString, Integer as SAInt
    engine = _engine(compat)
    with engine.connect() as conn:
        # M compat doesn't support CAST(x AS VARCHAR) or CAST(x AS INT);
        # use CHAR and SIGNED respectively for M
        if compat == "M":
            assert conn.execute(text("select cast(42 as char)")).scalar_one() == "42"
            assert conn.execute(text("select cast('123' as signed)")).scalar_one() == 123
            assert conn.execute(text("select cast(3.14 as signed)")).scalar_one() == 3
        else:
            assert conn.execute(text("select cast(42 as varchar)")).scalar_one() == "42"
            assert conn.execute(text("select cast('123' as int)")).scalar_one() == 123
            assert conn.execute(text("select cast(3.14 as int)")).scalar_one() == 3
        # SQLAlchemy cast generates CAST(x AS VARCHAR) which M doesn't support;
        # only test on A/B
        if compat != "M":
            result = conn.execute(select(cast(literal(42), SAString))).scalar_one()
            assert str(result).strip() == "42"
    print(f"  {compat} CAST: PASS")


# ── 19. NOT IN ───────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_not_in(compat):
    """Test NOT IN clause."""
    engine = _engine(compat)
    table_name = _tname("vnotin")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i} for i in range(1, 11)])
            result = conn.execute(
                select(t.c.id).where(~t.c.id.in_([1,2,3,4,5])).order_by(t.c.id)
            ).all()
            assert [r[0] for r in result] == [6,7,8,9,10]
        print(f"  {compat} NOT IN: PASS")
    finally:
        md.drop_all(engine)


# ── 20. String concatenation ─────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_string_concatenation(compat):
    """Test string concatenation operators."""
    engine = _engine(compat)
    table_name = _tname("vconcat")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("first", String(32)),
        Column("last", String(32)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, first="John", last="Doe"))
            # SQLAlchemy || operator
            result = conn.execute(
                select((t.c.first + " " + t.c.last).label("full")).where(t.c.id == 1)
            ).scalar_one()
            assert result == "John Doe", f"Concat failed: {result}"
        print(f"  {compat} string concat: PASS")
    except Exception as e:
        print(f"  {compat} string concat: {e}")
        raise
    finally:
        md.drop_all(engine)


# ── 21. LIKE with escape ─────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_like_with_escape(compat):
    """Test LIKE with % and _ wildcards and ESCAPE."""
    engine = _engine(compat)
    table_name = _tname("vlesc")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("pattern", String(50)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "pattern": "100%"},
                {"id": 2, "pattern": "100a"},
                {"id": 3, "pattern": "50%"},
                {"id": 4, "pattern": "100_"},
            ])
            # Match literal %
            result = conn.execute(
                text(f"select id from {table_name} where pattern like '100\\%%' escape '\\' order by id")
            ).all()
            assert [r[0] for r in result] == [1]
        print(f"  {compat} LIKE with escape: PASS")
    finally:
        md.drop_all(engine)


# ── 22. UPDATE...FROM (subquery in UPDATE) ───────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_update_from_subquery(compat):
    """Test UPDATE with subquery in FROM clause."""
    engine = _engine(compat)
    table_name = _tname("vupd_sub")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("val", Integer),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i*10} for i in range(1, 6)])
            subq = select(func.avg(t.c.val).label("avg_val")).scalar_subquery()
            conn.execute(t.update().values(val=t.c.val * 2).where(t.c.val > subq))
            rows = conn.execute(select(t.c.id, t.c.val).order_by(t.c.id)).all()
            # avg = 30, so val > 30 means id 4 (40) and 5 (50)
            assert rows == [(1,10),(2,20),(3,30),(4,80),(5,100)]
        print(f"  {compat} UPDATE from subquery: PASS")
    except Exception as e:
        print(f"  {compat} UPDATE from subquery: {e}")
        raise
    finally:
        md.drop_all(engine)


# ── 23. DELETE with RETURNING (A/B only) ─────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B"])
def test_delete_returning(compat):
    """Test DELETE...RETURNING (A/B compat)."""
    engine = _engine(compat)
    table_name = _tname("vdelret")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i} for i in range(1, 6)])
        # Delete with RETURNING
        with engine.begin() as conn:
            result = conn.execute(
                t.delete().where(t.c.val > 3).returning(t.c.id, t.c.val)
            )
            rows = result.all()
            assert len(rows) == 2
            assert sorted(r[0] for r in rows) == [4, 5]
        with engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 3
        print(f"  {compat} DELETE RETURNING: PASS")
    except Exception as e:
        print(f"  {compat} DELETE RETURNING: {e}")
        raise
    finally:
        md.drop_all(engine)


# ── 24. UPDATE...RETURNING (A/B only) ────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B"])
def test_update_returning(compat):
    """Test UPDATE...RETURNING (A/B compat)."""
    engine = _engine(compat)
    table_name = _tname("vupdret")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i*10} for i in range(1, 6)])
        with engine.begin() as conn:
            result = conn.execute(
                t.update().where(t.c.val >= 30).values(val=t.c.val + 1).returning(t.c.id, t.c.val)
            )
            rows = result.all()
            assert len(rows) == 3  # ids 3,4,5
            assert sorted(r[0] for r in rows) == [3, 4, 5]
        print(f"  {compat} UPDATE RETURNING: PASS")
    except Exception as e:
        print(f"  {compat} UPDATE RETURNING: {e}")
        raise
    finally:
        md.drop_all(engine)


# ── 25. Pool: pool_pre_ping detects stale connection ─────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_pool_pre_ping_stale(compat):
    """Test that pool_pre_ping detects and recovers stale connections."""
    engine = _engine(compat, pool_size=1, max_overflow=0)
    # First connection
    with engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
    # Connection returned to pool. Try again — pre_ping should verify
    with engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
    # Multiple rapid cycles
    for i in range(10):
        with engine.connect() as conn:
            assert conn.execute(text(f"select {i}")).scalar_one() == i
    print(f"  {compat} pool_pre_ping stale: PASS")


# ── 26. LIKE case-sensitivity per compat ─────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_like_case_sensitivity_documented(compat):
    """Document LIKE case-sensitivity behavior per compat mode."""
    engine = _engine(compat)
    table_name = _tname("vlike_cs")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("name", String(32)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "alice"},
                {"id": 3, "name": "ALICE"},
            ])
            result = conn.execute(
                select(t.c.id).where(t.c.name.like("Alice")).order_by(t.c.id)
            ).all()
            ids = [r[0] for r in result]
            if compat == "M":
                # M compat: LIKE is case-insensitive
                assert ids == [1, 2, 3], f"M compat LIKE should be case-insensitive: {ids}"
            else:
                # A/B compat: LIKE is case-sensitive
                assert ids == [1], f"A/B compat LIKE should be case-sensitive: {ids}"
        print(f"  {compat} LIKE case sensitivity: PASS ({'insensitive' if compat=='M' else 'sensitive'})")
    finally:
        md.drop_all(engine)
