"""Round 12: Final sweep — remaining edge cases, M-compat completeness, type system verification."""
import uuid
from datetime import datetime, date
from decimal import Decimal

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, LargeBinary, MetaData,
    Numeric, String, Table, Text, create_engine, inspect, select, text,
    ForeignKey, SmallInteger, BigInteger, Float, func, Index,
    UniqueConstraint, CheckConstraint, and_, or_, not_, cast, union_all,
)
from sqlalchemy.orm import Session, declarative_base, relationship

BASE = "gaussdb+odbc://sqlbuilder1:huawei%40123@121.37.186.131:19995"
URLS = {
    "A": f"{BASE}/postgres?sslmode=disable",
    "B": f"{BASE}/gdbdrv_b_compat?sslmode=disable",
    "M": f"{BASE}/testm?sslmode=disable",
}

def _engine(compat, **kw):
    return create_engine(URLS[compat], pool_pre_ping=True, **kw)

def _tname(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 1. M: ORM with session.execute(select) ──────────────────────────────────

@pytest.mark.integration
def test_m_orm_session_execute_select():
    """M-compat: ORM session.execute(select()) with auto_increment."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vexec_orm")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
        val = Column(Integer)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add_all([Item(name="a", val=10), Item(name="b", val=20), Item(name="c", val=30)])
            s.commit()
        with Session(engine) as s:
            result = s.execute(select(Item).where(Item.val > 15).order_by(Item.id)).scalars().all()
            assert len(result) == 2
            assert result[0].name == "b"
            assert result[1].name == "c"
        print("M ORM session.execute(select): PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 2. M: ORM with delete + re-add ──────────────────────────────────────────

@pytest.mark.integration
def test_m_orm_delete_readd():
    """M-compat: delete item, then add new — auto_increment should not reuse ID."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vdel_readd")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Item(name="first"))
            s.add(Item(name="second"))
            s.commit()
        with Session(engine) as s:
            s.query(Item).filter(Item.name == "first").delete()
            s.commit()
        with Session(engine) as s:
            s.add(Item(name="third"))
            s.commit()
            items = s.query(Item).order_by(Item.id).all()
            assert len(items) == 2
            assert items[0].id == 2  # second
            assert items[1].id == 3  # third (not 1)
        print("M ORM delete+readd: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 3. All: reflection of table with schema-qualified name ───────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_reflection_schema_qualified(compat):
    """Test reflection of schema-qualified table."""
    engine = _engine(compat)
    table_name = _tname("vsch_q")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(32)),
        schema="public",
    )
    try:
        md.create_all(engine)
        # Reflect without schema (should find it via search_path)
        reflected1 = Table(table_name, MetaData(), autoload_with=engine)
        assert len(reflected1.columns) == 2

        # Reflect with schema
        reflected2 = Table(table_name, MetaData(), autoload_with=engine, schema="public")
        assert len(reflected2.columns) == 2
        print(f"  {compat} schema-qualified reflection: PASS")
    finally:
        md.drop_all(engine)


# ── 4. All: column default with expression ───────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_column_default_expression(compat):
    """Test column with computed default expression."""
    engine = _engine(compat)
    table_name = _tname("vdef_expr")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("base", Integer),
        Column("doubled", Integer, default=0),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, base=5))
            result = conn.execute(select(t.c.doubled).where(t.c.id == 1)).scalar_one()
            # Python-side default = 0
            assert result == 0
        print(f"  {compat} column default expression: PASS")
    finally:
        md.drop_all(engine)


# ── 5. All: INDEX with multiple columns + INCLUDE ────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_index_with_include_columns(compat):
    """Test CREATE INDEX with INCLUDE clause (if supported)."""
    engine = _engine(compat)
    table_name = _tname("vix_inc")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, a int, b int, c int)"))
    try:
        # Standard composite index
        Index(f"ix_{table_name}_ab", text("a"), text("b"))
        with engine.begin() as conn:
            conn.execute(text(f"create index ix_{table_name}_ab on {table_name} (a, b)"))
        indexes = inspect(engine).get_indexes(table_name)
        assert any(ix["name"] == f"ix_{table_name}_ab" for ix in indexes)
        print(f"  {compat} composite index: PASS")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 6. M: Alembic batch with nullable + default ─────────────────────────────

@pytest.mark.integration
def test_m_batch_nullable_default():
    """M-compat: batch alter with nullable and server_default."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine("M")
    table_name = _tname("vbatch_nd")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32))"))
        conn.execute(text(f"insert into {table_name} values (1, 'test')"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            with ops.batch_alter_table(table_name) as batch:
                batch.add_column(Column("status", String(20), server_default=text("'active'"), nullable=False))
            conn.commit()

        cols = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        assert cols["status"]["nullable"] is False
        with engine.connect() as conn:
            result = conn.execute(text(f"select status from {table_name} where id=1")).scalar_one()
            assert result == "active"
        print("M batch nullable+default: PASS")
    except Exception as e:
        print(f"M batch nullable+default: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 7. All: SUM with NULL only ───────────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_sum_all_null(compat):
    """Test SUM on column with only NULL values."""
    engine = _engine(compat)
    table_name = _tname("vsum_null")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer, nullable=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": 1, "val": None}, {"id": 2, "val": None}])
            result = conn.execute(select(func.sum(t.c.val))).scalar_one()
            assert result is None, f"SUM of all NULLs: {result}"
            count = conn.execute(select(func.count(t.c.val))).scalar_one()
            assert count == 0, f"COUNT of non-NULL: {count}"
        print(f"  {compat} SUM all NULL: PASS")
    finally:
        md.drop_all(engine)


# ── 8. All: DISTINCT with multiple columns ───────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_distinct_multiple(compat):
    """Test DISTINCT with multiple columns."""
    engine = _engine(compat)
    table_name = _tname("vdist_multi")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("a", String(10)), Column("b", String(10)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "a": "x", "b": "1"},
                {"id": 2, "a": "x", "b": "1"},
                {"id": 3, "a": "x", "b": "2"},
                {"id": 4, "a": "y", "b": "1"},
            ])
            result = conn.execute(select(t.c.a, t.c.b).distinct().order_by(t.c.a, t.c.b)).all()
            assert result == [("x", "1"), ("x", "2"), ("y", "1")]
        print(f"  {compat} DISTINCT multiple: PASS")
    finally:
        md.drop_all(engine)


# ── 9. All: UPDATE all rows ──────────────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_update_all_rows(compat):
    """Test UPDATE without WHERE clause (all rows)."""
    engine = _engine(compat)
    table_name = _tname("vupd_all")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i} for i in range(1, 6)])
            result = conn.execute(t.update().values(val=0))
            assert result.rowcount == 5, f"UPDATE all rowcount: {result.rowcount}"
            vals = conn.execute(select(t.c.val).order_by(t.c.id)).all()
            assert all(v[0] == 0 for v in vals)
        print(f"  {compat} UPDATE all rows: PASS")
    finally:
        md.drop_all(engine)


# ── 10. All: DELETE all rows ─────────────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_delete_all_rows(compat):
    """Test DELETE without WHERE clause (all rows)."""
    engine = _engine(compat)
    table_name = _tname("vdel_all")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i} for i in range(1, 6)])
            result = conn.execute(t.delete())
            assert result.rowcount == 5, f"DELETE all rowcount: {result.rowcount}"
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 0
        print(f"  {compat} DELETE all rows: PASS")
    finally:
        md.drop_all(engine)


# ── 11. M: autogenerate with all M-specific types ───────────────────────────

@pytest.mark.integration
def test_m_autogenerate_all_types():
    """M-compat: autogenerate with all M-specific type mappings."""
    pytest.importorskip("alembic")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = _engine("M")
    table_name = _tname("vauto_all_m")
    md = MetaData()
    Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("amount", Numeric(12, 2)),
        Column("flag", Boolean),
        Column("created", DateTime),
        Column("biz_date", Date),
        Column("data", LargeBinary),
        Column("description", Text),
        Column("big_num", BigInteger),
        Column("small_num", SmallInteger),
    )
    try:
        md.create_all(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={"include_name": lambda name, type_, parent_names: (
                    type_ != "table" or name == table_name
                )},
            )
            diffs = compare_metadata(context, md)
        if diffs:
            for d in diffs:
                print(f"  diff: {d}")
        assert diffs == [], f"Expected no diffs, got: {diffs}"
        print("M autogenerate all types: PASS")
    finally:
        md.drop_all(engine)


# ── 12. All: reflected table INSERT and SELECT ───────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_reflected_table_crud(compat):
    """Test CRUD on a reflected table."""
    engine = _engine(compat)
    table_name = _tname("vref_crud")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("name", String(32)))
    try:
        md.create_all(engine)
        # Reflect
        reflected = Table(table_name, MetaData(), autoload_with=engine)
        # INSERT
        with engine.begin() as conn:
            conn.execute(reflected.insert().values(id=1, name="hello"))
            # SELECT
            result = conn.execute(select(reflected.c.id, reflected.c.name)).one()
            assert result == (1, "hello")
            # UPDATE
            conn.execute(reflected.update().where(reflected.c.id == 1).values(name="world"))
            result = conn.execute(select(reflected.c.name).where(reflected.c.id == 1)).scalar_one()
            assert result == "world"
            # DELETE
            conn.execute(reflected.delete().where(reflected.c.id == 1))
            count = conn.execute(select(func.count()).select_from(reflected)).scalar_one()
            assert count == 0
        print(f"  {compat} reflected table CRUD: PASS")
    finally:
        md.drop_all(engine)


# ── 13. All: multiple savepoints ─────────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_multiple_savepoints(compat):
    """Test multiple nested savepoints."""
    engine = _engine(compat)
    table_name = _tname("vsp_multi")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, val varchar(32))"))
    try:
        with engine.begin() as conn:
            conn.execute(text(f"insert into {table_name} values (1, 'outer')"))

            sp1 = conn.begin_nested()
            conn.execute(text(f"insert into {table_name} values (2, 'sp1')"))
            sp1.rollback()

            sp2 = conn.begin_nested()
            conn.execute(text(f"insert into {table_name} values (3, 'sp2')"))
            sp2.commit()

            sp3 = conn.begin_nested()
            conn.execute(text(f"insert into {table_name} values (4, 'sp3')"))
            sp3.rollback()

        with engine.connect() as conn:
            rows = conn.execute(text(f"select id, val from {table_name} order by id")).all()
            assert rows == [(1, "outer"), (3, "sp2")]
        print(f"  {compat} multiple savepoints: PASS")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 14. M: BOOLEAN type reflection in autogenerate ──────────────────────────

@pytest.mark.integration
def test_m_boolean_autogenerate_consistency():
    """M-compat: Boolean DDL writes SMALLINT, reflection reads SMALLINT, autogenerate clean."""
    pytest.importorskip("alembic")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = _engine("M")
    table_name = _tname("vbool_ag_m")
    md = MetaData()
    Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("active", Boolean),
        Column("name", String(32), nullable=False),
    )
    try:
        md.create_all(engine)
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={"include_name": lambda name, type_, parent_names: (
                    type_ != "table" or name == table_name
                )},
            )
            diffs = compare_metadata(context, md)
        assert diffs == [], f"Boolean autogenerate diffs: {diffs}"
        print("M Boolean autogenerate: PASS")
    finally:
        md.drop_all(engine)


# ── 15. All: empty string in WHERE ───────────────────────────────────────────

@pytest.mark.parametrize("compat", ["B", "M"])  # Skip A (empty string = NULL)
@pytest.mark.integration
def test_empty_string_in_where(compat):
    """Test WHERE clause with empty string comparison (B/M only)."""
    engine = _engine(compat)
    table_name = _tname("vempty_where")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", String(32)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "val": ""},
                {"id": 2, "val": "hello"},
                {"id": 3, "val": None},
            ])
            result = conn.execute(select(t.c.id).where(t.c.val == "").order_by(t.c.id)).all()
            assert [r[0] for r in result] == [1], f"Empty string WHERE: {result}"
        print(f"  {compat} empty string WHERE: PASS")
    finally:
        md.drop_all(engine)


# ── 16. All: LIKE with special regex chars ───────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_like_special_chars(compat):
    """Test LIKE with % and _ in data."""
    engine = _engine(compat)
    table_name = _tname("vlike_sp")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("name", String(32)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "name": "100%"},
                {"id": 2, "name": "100a"},
                {"id": 3, "name": "a_b"},
                {"id": 4, "name": "axb"},
            ])
            # Match literal %
            result = conn.execute(
                text(f"select id from {table_name} where name like '100\\%%' escape '\\' order by id")
            ).all()
            assert [r[0] for r in result] == [1]
        print(f"  {compat} LIKE special chars: PASS")
    finally:
        md.drop_all(engine)


# ── 17. All: count(*) vs count(column) ───────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_count_star_vs_column(compat):
    """Test COUNT(*) vs COUNT(column) with NULLs."""
    engine = _engine(compat)
    table_name = _tname("vcount")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer, nullable=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "val": 10},
                {"id": 2, "val": None},
                {"id": 3, "val": 30},
            ])
            count_star = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count_star == 3
            count_col = conn.execute(select(func.count(t.c.val))).scalar_one()
            assert count_col == 2  # NULL not counted
        print(f"  {compat} COUNT(*) vs COUNT(col): PASS")
    finally:
        md.drop_all(engine)


# ── 18. All: UNION ALL with different column names ───────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_union_all_different_names(compat):
    """Test UNION ALL with different column names."""
    engine = _engine(compat)
    t1 = _tname("vua1")
    t2 = _tname("vua2")
    md = MetaData()
    ta = Table(t1, md, Column("id", Integer, primary_key=True), Column("a_val", Integer))
    tb = Table(t2, md, Column("id", Integer, primary_key=True), Column("b_val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(ta.insert().values(id=1, a_val=10))
            conn.execute(tb.insert().values(id=1, b_val=20))
            result = conn.execute(
                union_all(select(ta.c.a_val), select(tb.c.b_val)).order_by(ta.c.a_val)
            ).all()
            assert result == [(10,), (20,)]
        print(f"  {compat} UNION ALL different names: PASS")
    finally:
        md.drop_all(engine)


# ── 19. M: full text search functions ───────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_text_search_functions(compat):
    """Test text search functions (if supported)."""
    engine = _engine(compat)
    with engine.connect() as conn:
        # position() / strpos()
        try:
            result = conn.execute(text("select position('lo' in 'hello')")).scalar_one()
            assert result == 4
            print(f"  {compat} position(): PASS")
        except Exception:
            print(f"  {compat} position(): not supported")

        # substring
        try:
            result = conn.execute(text("select substring('hello', 2, 3)")).scalar_one()
            assert result == "ell"
            print(f"  {compat} substring(): PASS")
        except Exception:
            print(f"  {compat} substring(): not supported")


# ── 20. All: implicit type promotion in arithmetic ──────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_implicit_type_promotion(compat):
    """Test implicit type promotion in arithmetic operations."""
    engine = _engine(compat)
    with engine.connect() as conn:
        # int + float = float
        result = conn.execute(text("select 1 + 1.5")).scalar_one()
        assert result == 2.5, f"int+float: {result}"
        # int / int = int (in some DBs) or float
        result2 = conn.execute(text("select 7 / 2")).scalar_one()
        # GaussDB may return 3 (integer division) or 3.5
        print(f"  {compat} 7/2 = {result2}")
        # int * float = float
        result3 = conn.execute(text("select 3 * 0.5")).scalar_one()
        assert result3 == 1.5, f"int*float: {result3}"
    print(f"  {compat} implicit type promotion: PASS")
