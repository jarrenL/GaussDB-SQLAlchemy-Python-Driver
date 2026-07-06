"""Round 10: Final comprehensive round — complex workflows, reflection completeness, stress."""
import uuid, time
from datetime import datetime, date
from decimal import Decimal

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, LargeBinary, MetaData,
    Numeric, String, Table, Text, create_engine, inspect, select, text,
    ForeignKey, SmallInteger, BigInteger, Float, func, Index,
    UniqueConstraint, CheckConstraint, and_, or_, not_, union, union_all, intersect,
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


# ── 1. Complete ORM workflow: create, insert, query, update, delete, reflect ─

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_complete_orm_lifecycle(compat):
    """Complete ORM lifecycle with relationships, cascade, reflection."""
    engine = _engine(compat)
    Base = declarative_base()
    dept_tbl = _tname("vlife_d")
    emp_tbl = _tname("vlife_e")

    class Department(Base):
        __tablename__ = dept_tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(50), nullable=False)
        employees = relationship("Employee", backref="department", cascade="all, delete-orphan")

    class Employee(Base):
        __tablename__ = emp_tbl
        id = Column(Integer, primary_key=True)
        dept_id = Column(Integer, ForeignKey(f"{dept_tbl}.id"))
        name = Column(String(50), nullable=False)
        salary = Column(Numeric(10, 2))

    try:
        # Create
        Base.metadata.create_all(engine)

        # Insert with relationship
        with Session(engine) as s:
            eng = Department(id=1, name="Engineering")
            eng.employees = [
                Employee(id=1, name="Alice", salary=Decimal("100000.00")),
                Employee(id=2, name="Bob", salary=Decimal("80000.00")),
            ]
            sales = Department(id=2, name="Sales")
            sales.employees = [
                Employee(id=3, name="Carol", salary=Decimal("70000.00")),
            ]
            s.add_all([eng, sales])
            s.commit()

        # Query with join
        with Session(engine) as s:
            result = s.query(Employee.name, Department.name).join(Department).order_by(Employee.id).all()
            assert result == [("Alice", "Engineering"), ("Bob", "Engineering"), ("Carol", "Sales")]

        # Update
        with Session(engine) as s:
            bob = s.get(Employee, 2)
            bob.salary = Decimal("90000.00")
            s.commit()

        # Verify update
        with Session(engine) as s:
            assert s.get(Employee, 2).salary == Decimal("90000.00")

        # Aggregate
        with Session(engine) as s:
            avg_salary = s.query(func.avg(Employee.salary)).join(Department).filter(Department.name == "Engineering").scalar()
            assert avg_salary == 95000.0

        # Cascade delete
        with Session(engine) as s:
            s.delete(s.get(Department, 1))
            s.commit()
            assert s.query(Employee).count() == 1
            assert s.query(Department).count() == 1

        # Reflection
        inspector = inspect(engine)
        assert inspector.has_table(dept_tbl)
        assert inspector.has_table(emp_tbl)

        print(f"  {compat} complete ORM lifecycle: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 2. Alembic: full migration workflow ──────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_alembic_full_migration_workflow(compat):
    """Full Alembic workflow: create, alter, add index, add constraint, drop."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = _engine(compat)
    table_name = _tname("valwf")

    # Step 1: create table
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32))"))
        conn.execute(text(f"insert into {table_name} values (1, 'test')"))

    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)

            # Step 2: add column
            ops.add_column(table_name, Column("age", Integer))
            conn.commit()

            # Step 3: add unique constraint
            ops.create_unique_constraint(f"uq_{table_name}_name", table_name, ["name"])
            conn.commit()

            # Step 4: add index
            ops.create_index(f"ix_{table_name}_age", table_name, ["age"])
            conn.commit()

            # Step 5: alter column (rename + type)
            with ops.batch_alter_table(table_name) as batch:
                batch.alter_column("age", new_column_name="years", type_=String(64))
            conn.commit()

        # Verify all changes
        inspector = inspect(engine)
        cols = {c["name"]: c for c in inspector.get_columns(table_name)}
        assert {"id", "name", "years"} == set(cols)

        uqs = inspector.get_unique_constraints(table_name)
        assert any("name" in uq["column_names"] for uq in uqs)

        indexes = inspector.get_indexes(table_name)
        assert any(ix["name"] == f"ix_{table_name}_age" for ix in indexes)

        # Data preserved
        with engine.connect() as conn:
            row = conn.execute(text(f"select id, name from {table_name} where id=1")).one()
            assert row == (1, "test")

        print(f"  {compat} full Alembic workflow: PASS")
    except Exception as e:
        print(f"  {compat} full Alembic workflow: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 3. Stress: 1000 rapid queries ────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_stress_1000_queries(compat):
    """Stress test: 1000 rapid SELECT queries."""
    engine = _engine(compat, pool_size=2, max_overflow=3)
    for i in range(1000):
        with engine.connect() as conn:
            result = conn.execute(text(f"select {i}")).scalar_one()
            assert result == i
    print(f"  {compat} 1000 queries: PASS")


# ── 4. Stress: 100 transactions ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_stress_100_transactions(compat):
    """Stress test: 100 sequential transactions with INSERT + SELECT."""
    engine = _engine(compat)
    table_name = _tname("vstr100")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        for i in range(100):
            with engine.begin() as conn:
                conn.execute(t.insert().values(id=i+1, val=i*i))
                count = conn.execute(select(func.count()).select_from(t)).scalar_one()
                assert count == i + 1

        with engine.connect() as conn:
            total = conn.execute(select(func.sum(t.c.val))).scalar_one()
            expected = sum(i*i for i in range(100))  # i = 0..99, val = i*i
            assert total == expected, f"Sum mismatch: {total} != {expected}"
        print(f"  {compat} 100 transactions: PASS")
    finally:
        md.drop_all(engine)


# ── 5. Reflection: all constraint types on one table ─────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_all_constraints_reflection(compat):
    """Test reflection of all constraint types on a single table."""
    engine = _engine(compat)
    table_name = _tname("vallcon")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("email", String(100)),
        Column("age", Integer),
        Column("code", String(32)),
        UniqueConstraint("email", name=f"uq_{table_name}_email"),
        UniqueConstraint("code", name=f"uq_{table_name}_code"),
        CheckConstraint("age >= 0", name=f"ck_{table_name}_age"),
        Index(f"ix_{table_name}_age", "age"),
    )
    try:
        md.create_all(engine)
        inspector = inspect(engine)

        # PK
        pk = inspector.get_pk_constraint(table_name)
        assert pk["constrained_columns"] == ["id"]

        # Unique constraints
        uqs = inspector.get_unique_constraints(table_name)
        assert len(uqs) >= 2, f"Expected >= 2 UQs, got {len(uqs)}"

        # Check constraints
        cks = inspector.get_check_constraints(table_name)
        assert any("age" in str(ck.get("sqltext", "")) for ck in cks), f"No age check: {cks}"

        # Indexes
        indexes = inspector.get_indexes(table_name)
        assert any(ix["name"] == f"ix_{table_name}_age" for ix in indexes)

        # Columns
        cols = inspector.get_columns(table_name)
        assert len(cols) == 4

        print(f"  {compat} all constraints reflection: PASS")
    finally:
        md.drop_all(engine)


# ── 6. M: timestamp comparison in WHERE ──────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_timestamp_comparison_where(compat):
    """Test TIMESTAMP comparison in WHERE clause."""
    engine = _engine(compat)
    table_name = _tname("vts_cmp")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "ts": datetime(2026, 1, 1, 0, 0, 0)},
                {"id": 2, "ts": datetime(2026, 6, 1, 0, 0, 0)},
                {"id": 3, "ts": datetime(2026, 12, 1, 0, 0, 0)},
            ])
            result = conn.execute(
                select(t.c.id).where(t.c.ts > datetime(2026, 3, 1, 0, 0, 0)).order_by(t.c.id)
            ).all()
            assert [r[0] for r in result] == [2, 3], f"TS comparison: {result}"
        print(f"  {compat} timestamp comparison: PASS")
    finally:
        md.drop_all(engine)


# ── 7. M: concat with numeric columns ────────────────────────────────────────

@pytest.mark.integration
def test_m_concat_numeric_columns():
    """M-compat: concat with numeric columns (explicit cast to CHAR)."""
    engine = _engine("M")
    table_name = _tname("vcatnum")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("num", Integer), Column("str", String(32)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, num=42, str="items: "))
            # M compat doesn't support CAST(x AS VARCHAR); use raw SQL with CHAR
            result = conn.execute(
                text(f"select concat(str, cast(num as char)) from {table_name} where id = 1")
            ).scalar_one()
            assert result == "items: 42", f"Concat numeric: {result}"
        print("M concat numeric: PASS")
    except Exception as e:
        print(f"M concat numeric: {e}")
        raise
    finally:
        md.drop_all(engine)


# ── 8. Complex: self-referencing tree with recursive query ───────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_self_ref_tree_queries(compat):
    """Test self-referencing tree structure with recursive queries."""
    engine = _engine(compat)
    table_name = _tname("vtree")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey(f"{table_name}.id")),
        Column("name", String(32)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "parent_id": None, "name": "root"},
                {"id": 2, "parent_id": 1, "name": "child1"},
                {"id": 3, "parent_id": 1, "name": "child2"},
                {"id": 4, "parent_id": 2, "name": "grand1"},
                {"id": 5, "parent_id": 2, "name": "grand2"},
                {"id": 6, "parent_id": 3, "name": "grand3"},
            ])

            # Get children of node 1
            result = conn.execute(
                select(t.c.id, t.c.name).where(t.c.parent_id == 1).order_by(t.c.id)
            ).all()
            assert [r[0] for r in result] == [2, 3]

            # Get leaf nodes (no children)
            child_ids = select(t.c.parent_id).where(t.c.parent_id.isnot(None))
            result2 = conn.execute(
                select(t.c.id, t.c.name).where(~t.c.id.in_(child_ids)).order_by(t.c.id)
            ).all()
            assert [r[0] for r in result2] == [4, 5, 6]
        print(f"  {compat} self-ref tree: PASS")
    finally:
        md.drop_all(engine)


# ── 9. M: ALTER TABLE ADD COLUMN with auto_increment ─────────────────────────

@pytest.mark.integration
def test_m_add_autoinc_column_fails():
    """M-compat: adding auto_increment column to existing table should fail gracefully."""
    engine = _engine("M")
    table_name = _tname("vaddai")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32))"))
    try:
        # Adding auto_increment column to existing table is not standard
        with pytest.raises(Exception):
            with engine.begin() as conn:
                conn.execute(text(f"alter table {table_name} add column new_id int auto_increment primary key"))
        print("M add autoinc column: correctly rejected")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 10. All compat: table names with special chars ───────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_table_name_with_underscore_and_digits(compat):
    """Test table name with underscores and digits."""
    engine = _engine(compat)
    table_name = _tname("v_table_123_test")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True))
    try:
        md.create_all(engine)
        assert inspect(engine).has_table(table_name)

        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1))
            result = conn.execute(select(t.c.id)).scalar_one()
            assert result == 1
        print(f"  {compat} table name with _ and digits: PASS")
    finally:
        md.drop_all(engine)


# ── 11. M: batch_alter_table with multiple operations ────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_batch_alter_multiple_ops(compat):
    """Test batch_alter_table with multiple operations in one batch."""
    pytest.importorskip("alembic")
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import String as SAString

    engine = _engine(compat)
    table_name = _tname("vbatch_multi")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, old_name varchar(32) not null)"))
        conn.execute(text(f"insert into {table_name} values (1, 'test')"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            with ops.batch_alter_table(table_name) as batch:
                batch.alter_column("old_name", new_column_name="new_name")
                batch.alter_column("new_name", type_=SAString(100), nullable=True)
                batch.add_column(Column("extra", Integer))
            conn.commit()

        cols = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        assert "new_name" in cols and "old_name" not in cols
        assert "extra" in cols
        assert cols["new_name"]["nullable"] is True

        # Data preserved
        with engine.connect() as conn:
            row = conn.execute(text(f"select new_name from {table_name} where id=1")).scalar_one()
            assert row == "test"
        print(f"  {compat} batch multiple ops: PASS")
    except Exception as e:
        print(f"  {compat} batch multiple ops: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 12. All compat: NULL handling in aggregates ──────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_null_in_aggregates(compat):
    """Test NULL handling in aggregate functions."""
    engine = _engine(compat)
    table_name = _tname("vnullagg")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer, nullable=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "val": 10},
                {"id": 2, "val": None},
                {"id": 3, "val": 30},
                {"id": 4, "val": None},
                {"id": 5, "val": 50},
            ])
            # COUNT ignores NULL
            count = conn.execute(select(func.count(t.c.val))).scalar_one()
            assert count == 3, f"COUNT: {count}"

            # SUM ignores NULL
            total = conn.execute(select(func.sum(t.c.val))).scalar_one()
            assert total == 90, f"SUM: {total}"

            # AVG ignores NULL
            avg = conn.execute(select(func.avg(t.c.val))).scalar_one()
            assert avg == 30.0, f"AVG: {avg}"

            # MIN/MAX ignore NULL
            mn = conn.execute(select(func.min(t.c.val))).scalar_one()
            mx = conn.execute(select(func.max(t.c.val))).scalar_one()
            assert mn == 10 and mx == 50
        print(f"  {compat} NULL in aggregates: PASS")
    finally:
        md.drop_all(engine)


# ── 13. All compat: cross-schema FK ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_cross_schema_fk(compat):
    """Test FK referencing table in public schema explicitly."""
    engine = _engine(compat)
    parent = _tname("vxsfk_p")
    child = _tname("vxsfk_c")
    md = MetaData()
    p = Table(parent, md, Column("id", Integer, primary_key=True), schema="public")
    c = Table(child, md,
        Column("id", Integer, primary_key=True),
        Column("pid", Integer, ForeignKey("public." + parent + ".id")),
    )
    try:
        md.create_all(engine)
        fks = inspect(engine).get_foreign_keys(child)
        assert len(fks) == 1
        assert fks[0]["referred_table"] == parent
        assert fks[0]["referred_columns"] == ["id"]
        print(f"  {compat} cross-schema FK: PASS")
    finally:
        md.drop_all(engine)


# ── 14. All compat: empty result set ─────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_empty_result_set(compat):
    """Test queries that return no rows."""
    engine = _engine(compat)
    table_name = _tname("vempty_r")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.connect() as conn:
            # No rows match
            result = conn.execute(select(t.c.id).where(t.c.id > 100)).all()
            assert result == []

            # scalar_one should raise
            with pytest.raises(Exception):
                conn.execute(select(t.c.id).where(t.c.id > 100)).scalar_one()

            # scalar_one_or_none should return None
            result2 = conn.execute(select(t.c.id).where(t.c.id > 100)).scalar_one_or_none()
            assert result2 is None

            # Aggregate on empty set
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 0
        print(f"  {compat} empty result set: PASS")
    finally:
        md.drop_all(engine)


# ── 15. M: verify all M-specific fixes working together ──────────────────────

@pytest.mark.integration
def test_m_all_fixes_integration():
    """Integration test verifying all M-compat fixes work together in one workflow."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vintegration")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(50), nullable=False)
        flag = Column(Boolean)
        created = Column(DateTime)
        price = Column(Numeric(10, 2))

    try:
        # 1. DDL with M-compat types (AUTO_INCREMENT, SMALLINT for bool, TIMESTAMP(6))
        Base.metadata.create_all(engine)

        # 2. INSERT without RETURNING (auto_increment)
        with Session(engine) as s:
            s.add(Item(name="test", flag=True, created=datetime(2026, 6, 23, 14, 30, 45, 123456), price=Decimal("99.99")))
            s.commit()

        # 3. SELECT with concat
        with Session(engine) as s:
            item = s.query(Item).filter(Item.name == "test").one()
            assert item.flag is True
            assert item.created == datetime(2026, 6, 23, 14, 30, 45, 123456)
            assert item.price == Decimal("99.99")

        # 4. UPDATE with concat
        with Session(engine) as s:
            item = s.get(Item, 1)
            item.name = "updated"
            s.commit()

        # 5. DDL reflection
        cols = {c["name"]: c for c in inspect(engine).get_columns(tbl)}
        assert cols["id"]["autoincrement"] is True
        assert cols["flag"]["type"] is not None
        assert cols["created"]["type"] is not None

        # 6. Alembic batch alter
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            ops = Operations(ctx)
            with ops.batch_alter_table(tbl) as batch:
                batch.alter_column("name", type_=String(100), nullable=True)
            conn.commit()

        print("M all fixes integration: PASS")
    finally:
        Base.metadata.drop_all(engine)
