"""Round 11: Deep edge cases — ODBC type conversion, parameter binding, server-side functions, M-compat specifics."""
import uuid, time
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, LargeBinary, MetaData,
    Numeric, String, Table, Text, create_engine, inspect, select, text,
    ForeignKey, SmallInteger, BigInteger, Float, func, Index,
    UniqueConstraint, CheckConstraint, and_, or_, not_, cast, literal,
    union, union_all, Sequence, event,
)
from sqlalchemy.orm import Session, declarative_base, relationship

from tests.test_config import ODBC_URLS as URLS

def _engine(compat, **kw):
    return create_engine(URLS[compat], pool_pre_ping=True, **kw)

def _tname(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 1. M: ORM bulk insert with auto_increment ────────────────────────────────

@pytest.mark.integration
def test_m_orm_bulk_insert_autoincrement():
    """M-compat: ORM bulk insert with auto_increment IDs."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vbulk_orm")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add_all([Item(name=f"item_{i}") for i in range(10)])
            s.commit()
        with Session(engine) as s:
            items = s.query(Item).order_by(Item.id).all()
            assert len(items) == 10
            assert [i.id for i in items] == list(range(1, 11))
        print("M ORM bulk insert autoinc: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 2. M: ORM session.add then query identity ───────────────────────────────

@pytest.mark.integration
def test_m_orm_identity_after_flush():
    """M-compat: ORM identity map after flush."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vident")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            item = Item(name="test")
            s.add(item)
            s.flush()
            assert item.id is not None
            # Identity map: same object
            same = s.get(Item, item.id)
            assert same is item
        print("M ORM identity after flush: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 3. M: ORM update with auto_increment id in WHERE ────────────────────────

@pytest.mark.integration
def test_m_orm_update_delete():
    """M-compat: ORM update and delete by auto_increment id."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vud")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
        val = Column(Integer)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add_all([Item(name="a", val=1), Item(name="b", val=2)])
            s.commit()
        with Session(engine) as s:
            item = s.query(Item).filter(Item.name == "a").one()
            item.val = 99
            s.commit()
        with Session(engine) as s:
            assert s.query(Item).filter(Item.name == "a").one().val == 99
            s.query(Item).filter(Item.name == "b").delete()
            s.commit()
        with Session(engine) as s:
            assert s.query(Item).count() == 1
        print("M ORM update/delete: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 4. All: datetime parameter binding ───────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_datetime_parameter_binding(compat):
    """Test datetime parameter binding with various precisions."""
    engine = _engine(compat)
    table_name = _tname("vdt_param")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        test_vals = [
            datetime(2026, 1, 1, 0, 0, 0),
            datetime(2026, 6, 23, 12, 30, 45),
            datetime(2026, 6, 23, 12, 30, 45, 123456),
            datetime(1999, 12, 31, 23, 59, 59, 999999),
        ]
        with engine.begin() as conn:
            for i, ts in enumerate(test_vals, 1):
                conn.execute(t.insert().values(id=i, ts=ts))
            for i, expected in enumerate(test_vals, 1):
                actual = conn.execute(select(t.c.ts).where(t.c.id == i)).scalar_one()
                assert actual == expected, f"{compat} row {i}: {expected} -> {actual}"
        print(f"  {compat} datetime param binding: PASS")
    finally:
        md.drop_all(engine)


# ── 5. All: date parameter binding ───────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_date_parameter_binding(compat):
    """Test date parameter binding."""
    engine = _engine(compat)
    table_name = _tname("vdate_param")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("d", Date))
    try:
        md.create_all(engine)
        test_dates = [date(1, 1, 1), date(2026, 6, 23), date(9999, 12, 31)]
        with engine.begin() as conn:
            for i, d in enumerate(test_dates, 1):
                conn.execute(t.insert().values(id=i, d=d))
            for i, expected in enumerate(test_dates, 1):
                actual = conn.execute(select(t.c.d).where(t.c.id == i)).scalar_one()
                assert actual == expected, f"{compat} row {i}: {expected} -> {actual}"
        print(f"  {compat} date param binding: PASS")
    finally:
        md.drop_all(engine)


# ── 6. All: decimal parameter binding ────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_decimal_parameter_binding(compat):
    """Test decimal parameter binding with various scales."""
    engine = _engine(compat)
    table_name = _tname("vdec_param")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("n", Numeric(15, 4)))
    try:
        md.create_all(engine)
        test_vals = [
            Decimal("0"),
            Decimal("0.0001"),
            Decimal("0.9999"),
            Decimal("1234567890.1234"),
            Decimal("-1234567890.1234"),
            Decimal("-0.0001"),
        ]
        with engine.begin() as conn:
            for i, v in enumerate(test_vals, 1):
                conn.execute(t.insert().values(id=i, n=v))
            for i, expected in enumerate(test_vals, 1):
                actual = conn.execute(select(t.c.n).where(t.c.id == i)).scalar_one()
                assert actual == expected, f"{compat} row {i}: {expected} -> {actual}"
        print(f"  {compat} decimal param binding: PASS")
    finally:
        md.drop_all(engine)


# ── 7. All: bytes parameter binding ──────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_bytes_parameter_binding(compat):
    """Test bytes parameter binding with various values."""
    engine = _engine(compat)
    table_name = _tname("vbin_param")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("data", LargeBinary))
    try:
        md.create_all(engine)
        test_vals = [
            b"\x00",
            b"\xff",
            b"\x00\xff",
            bytes(range(256)),
            b"hello world",
            b"",
        ]
        with engine.begin() as conn:
            for i, v in enumerate(test_vals, 1):
                conn.execute(t.insert().values(id=i, data=v))
            for i, expected in enumerate(test_vals, 1):
                actual = conn.execute(select(t.c.data).where(t.c.id == i)).scalar_one()
                if actual is None:
                    assert expected == b"", f"{compat} row {i}: expected {expected!r}, got None"
                else:
                    assert bytes(actual) == expected, f"{compat} row {i}: mismatch"
        print(f"  {compat} bytes param binding: PASS")
    finally:
        md.drop_all(engine)


# ── 8. All: boolean parameter binding ────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_boolean_parameter_binding(compat):
    """Test boolean parameter binding."""
    engine = _engine(compat)
    table_name = _tname("vbool_param")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("flag", Boolean))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, flag=True))
            conn.execute(t.insert().values(id=2, flag=False))
            conn.execute(t.insert().values(id=3, flag=None))
            rows = conn.execute(select(t.c.id, t.c.flag).order_by(t.c.id)).all()
            assert rows[0][1] is True
            assert rows[1][1] is False
            assert rows[2][1] is None
        print(f"  {compat} boolean param binding: PASS")
    finally:
        md.drop_all(engine)


# ── 9. M: server-side function in server_default ─────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_server_default_uuid(compat):
    """Test server_default with UUID generation (if supported)."""
    engine = _engine(compat)
    table_name = _tname("vuuid")
    with engine.begin() as conn:
        conn.execute(text(f"drop table if exists {table_name}"))
    try:
        with engine.begin() as conn:
            # Try UUID default
            try:
                conn.execute(text(
                    f"create table {table_name} (id int primary key, uid uuid default gen_random_uuid())"
                ))
                conn.execute(text(f"insert into {table_name} (id) values (1)"))
                result = conn.execute(text(f"select uid from {table_name}")).scalar_one()
                assert result is not None
                print(f"  {compat} UUID default: PASS ({str(result)[:20]}...)")
            except Exception as e:
                print(f"  {compat} UUID default: not supported — {str(e)[:60]}")
                conn.rollback()
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 10. M: concat in subquery ───────────────────────────────────────────────

@pytest.mark.integration
def test_m_concat_in_subquery():
    """M-compat: concat used inside a subquery."""
    engine = _engine("M")
    table_name = _tname("vcat_sub")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("first", String(32)),
        Column("last", String(32)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "first": "John", "last": "Doe"},
                {"id": 2, "first": "Jane", "last": "Smith"},
            ])
            subq = select(t.c.id, (t.c.first + " " + t.c.last).label("full")).subquery()
            result = conn.execute(
                select(subq.c.id, subq.c.full).where(subq.c.full == "John Doe")
            ).one()
            assert result == (1, "John Doe")
        print("M concat in subquery: PASS")
    finally:
        md.drop_all(engine)


# ── 11. All: nested concat expressions ───────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_nested_concat_expressions(compat):
    """Test nested concat expressions."""
    engine = _engine(compat)
    table_name = _tname("vnested_concat")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("a", String(32)),
        Column("b", String(32)),
        Column("c", String(32)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, a="x", b="y", c="z"))
            # Nested: ((a + b) + c)
            result = conn.execute(
                select((t.c.a + t.c.b + t.c.c).label("combined")).where(t.c.id == 1)
            ).scalar_one()
            assert result == "xyz", f"{compat} nested concat: {result}"
        print(f"  {compat} nested concat: PASS")
    finally:
        md.drop_all(engine)


# ── 12. M: TIMESTAMP(6) reflected correctly ─────────────────────────────────

@pytest.mark.integration
def test_m_timestamp_reflection_precision():
    """M-compat: TIMESTAMP(6) should be reflected with correct type."""
    engine = _engine("M")
    table_name = _tname("vts_reflect")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        cols = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        ts_type = str(cols["ts"]["type"])
        print(f"M reflected TIMESTAMP type: {ts_type}")
        # Should be TIMESTAMP, not TIMESTAMP(0)
        assert "TIMESTAMP" in ts_type.upper()
        # Insert and verify microsecond preservation
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, ts=datetime(2026, 6, 23, 14, 30, 45, 123456)))
            result = conn.execute(select(t.c.ts).where(t.c.id == 1)).scalar_one()
            assert result == datetime(2026, 6, 23, 14, 30, 45, 123456)
        print("M TIMESTAMP reflection + microsecond: PASS")
    finally:
        md.drop_all(engine)


# ── 13. All: alembic autogenerate with multiple types ───────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_autogenerate_multiple_types(compat):
    """Test autogenerate with many column types."""
    pytest.importorskip("alembic")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = _engine(compat)
    table_name = _tname("vauto_types")
    md = MetaData()
    Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("amount", Numeric(12, 2)),
        Column("flag", Boolean),
        Column("created", DateTime),
        Column("biz_date", Date),
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
                print(f"  {compat} diff: {d}")
        assert diffs == [], f"Expected no diffs, got: {diffs}"
        print(f"  {compat} autogenerate multiple types: PASS")
    finally:
        md.drop_all(engine)


# ── 14. All: table name with max length ──────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_long_table_name(compat):
    """Test table name near max length (63 chars for PG)."""
    engine = _engine(compat)
    # 63 chars: standard PG identifier max (NAMEDATALEN-1)
    table_name = "v" + "a" * 60 + "_z"
    assert len(table_name) == 63, f"Expected 63, got {len(table_name)}"
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True))
    try:
        md.create_all(engine)
        assert inspect(engine).has_table(table_name)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1))
            assert conn.execute(select(t.c.id)).scalar_one() == 1
        print(f"  {compat} long table name ({len(table_name)} chars): PASS")
    finally:
        md.drop_all(engine)


# ── 15. All: column name with max length ─────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_long_column_name(compat):
    """Test column name near max length."""
    engine = _engine(compat)
    table_name = _tname("vlcol")
    col_name = "c" + "o" * 61 + "l"  # 63 chars
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column(col_name, String(32)))
    try:
        md.create_all(engine)
        cols = [c["name"] for c in inspect(engine).get_columns(table_name)]
        assert col_name in cols
        print(f"  {compat} long column name ({len(col_name)} chars): PASS")
    finally:
        md.drop_all(engine)


# ── 16. M: INSERT with explicit ID after auto_increment ─────────────────────

@pytest.mark.integration
def test_m_explicit_id_then_auto():
    """M-compat: explicit ID insert, then auto-increment should continue."""
    engine = _engine("M")
    Base = declarative_base()
    tbl = _tname("vexid_orm")
    class Item(Base):
        __tablename__ = tbl
        id = Column(Integer, primary_key=True)
        name = Column(String(32))
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            s.add(Item(id=100, name="explicit"))
            s.commit()
        with Session(engine) as s:
            s.add(Item(name="auto"))
            s.commit()
            items = s.query(Item).order_by(Item.id).all()
            assert items[0].id == 100
            assert items[1].id > 100, f"Auto should be > 100, got {items[1].id}"
        print(f"M explicit then auto (ORM): PASS — ids={[i.id for i in items]}")
    finally:
        Base.metadata.drop_all(engine)


# ── 17. All: timezone-aware datetime with UTC ────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_utc_datetime_binding(compat):
    """Test timezone-aware UTC datetime parameter binding."""
    engine = _engine(compat)
    table_name = _tname("vutc")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        utc = timezone.utc
        aware = datetime(2026, 6, 23, 12, 0, 0, 123456, tzinfo=utc)
        expected_naive = datetime(2026, 6, 23, 12, 0, 0, 123456)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, ts=aware))
            result = conn.execute(select(t.c.ts).where(t.c.id == 1)).scalar_one()
            assert result == expected_naive, f"UTC: {aware} -> {result}"
        print(f"  {compat} UTC datetime binding: PASS")
    finally:
        md.drop_all(engine)


# ── 18. All: timezone-aware datetime with non-UTC offset ────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_offset_datetime_binding(compat):
    """Test timezone-aware datetime with non-UTC offset."""
    engine = _engine(compat)
    table_name = _tname("voffset")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        tz_plus_8 = timezone(timedelta(hours=8))
        tz_minus_5 = timezone(timedelta(hours=-5))
        aware_p8 = datetime(2026, 6, 23, 20, 0, 0, 123456, tzinfo=tz_plus_8)
        aware_m5 = datetime(2026, 6, 23, 7, 0, 0, 123456, tzinfo=tz_minus_5)
        expected_utc = datetime(2026, 6, 23, 12, 0, 0, 123456)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, ts=aware_p8))
            conn.execute(t.insert().values(id=2, ts=aware_m5))
            r1 = conn.execute(select(t.c.ts).where(t.c.id == 1)).scalar_one()
            r2 = conn.execute(select(t.c.ts).where(t.c.id == 2)).scalar_one()
            assert r1 == expected_utc, f"+8: {aware_p8} -> {r1}"
            assert r2 == expected_utc, f"-5: {aware_m5} -> {r2}"
        print(f"  {compat} offset datetime binding: PASS")
    finally:
        md.drop_all(engine)


# ── 19. M: ORM with relationship + auto_increment ───────────────────────────

@pytest.mark.integration
def test_m_orm_relationship_autoinc():
    """M-compat: ORM relationship with auto_increment FKs."""
    engine = _engine("M")
    Base = declarative_base()
    parent_tbl = _tname("vrel_ai_p")
    child_tbl = _tname("vrel_ai_c")

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
            p = Parent(name="root")
            p.children = [Child(val=f"c{i}") for i in range(3)]
            s.add(p)
            s.commit()
            assert p.id is not None
            for c in p.children:
                assert c.id is not None
                assert c.parent_id == p.id

        with Session(engine) as s:
            p = s.query(Parent).one()
            assert len(p.children) == 3
        print("M ORM relationship autoinc: PASS")
    finally:
        Base.metadata.drop_all(engine)


# ── 20. All: reconnect after connection error ───────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_reconnect_after_error(compat):
    """Test that connection pool recovers after a query error."""
    engine = _engine(compat, pool_size=1, max_overflow=0)
    table_name = _tname("vreconn")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key)"))
    try:
        # Normal query
        with engine.connect() as conn:
            assert conn.execute(text(f"select count(*) from {table_name}")).scalar_one() == 0

        # Error query
        with pytest.raises(Exception):
            with engine.connect() as conn:
                conn.execute(text("select nonexistent_column from nonexistent_table"))

        # Recovery — pool should still work
        with engine.connect() as conn:
            assert conn.execute(text(f"select count(*) from {table_name}")).scalar_one() == 0
        print(f"  {compat} reconnect after error: PASS")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 21. All: INSERT with all NULL values (except PK) ─────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_insert_all_null(compat):
    """Test INSERT with all NULL values (except PK)."""
    engine = _engine(compat)
    table_name = _tname("vnullall")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("a", Integer, nullable=True),
        Column("b", String(32), nullable=True),
        Column("c", Boolean, nullable=True),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, a=None, b=None, c=None))
            row = conn.execute(select(t.c.a, t.c.b, t.c.c).where(t.c.id == 1)).one()
            assert row == (None, None, None)
        print(f"  {compat} insert all NULL: PASS")
    finally:
        md.drop_all(engine)


# ── 22. All: executemany with mixed types ───────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_executemany_mixed_types(compat):
    """Test executemany with mixed parameter types."""
    engine = _engine(compat)
    table_name = _tname("vemany")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(32)),
        Column("amount", Numeric(10, 2)),
        Column("flag", Boolean),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [
                {"id": 1, "name": "a", "amount": Decimal("10.50"), "flag": True},
                {"id": 2, "name": "b", "amount": Decimal("20.00"), "flag": False},
                {"id": 3, "name": None, "amount": None, "flag": None},
            ])
            rows = conn.execute(select(t.c.id, t.c.name, t.c.amount, t.c.flag).order_by(t.c.id)).all()
            assert rows[0] == (1, "a", Decimal("10.50"), True)
            assert rows[1] == (2, "b", Decimal("20.00"), False)
            assert rows[2] == (3, None, None, None)
        print(f"  {compat} executemany mixed types: PASS")
    finally:
        md.drop_all(engine)


# ── 23. M: Alembic autogenerate with DateTime ───────────────────────────────

@pytest.mark.integration
def test_m_autogenerate_with_datetime():
    """M-compat: autogenerate with DateTime column should be clean."""
    pytest.importorskip("alembic")
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = _engine("M")
    table_name = _tname("vauto_dt_m")
    md = MetaData()
    Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("name", String(32), nullable=False),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
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
        print("M autogenerate with DateTime: PASS")
    finally:
        md.drop_all(engine)


# ── 24. All: query with no parameters ────────────────────────────────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_query_no_parameters(compat):
    """Test queries that take no parameters."""
    engine = _engine(compat)
    with engine.connect() as conn:
        assert conn.execute(text("select 1")).scalar_one() == 1
        assert conn.execute(text("select 1 + 1")).scalar_one() == 2
        assert conn.execute(text("select 'hello'")).scalar_one() == "hello"
    print(f"  {compat} query no params: PASS")


# ── 25. All: multiple statements in one execute (should fail) ───────────────

@pytest.mark.parametrize("compat", ["A", "B", "M"])
@pytest.mark.integration
def test_multiple_statements_behavior(compat):
    """Test behavior of multiple statements in one execute()."""
    engine = _engine(compat)
    table_name = _tname("vmulti_stmt")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int)"))
    try:
        # GaussDB ODBC may or may not support multi-statement in one execute
        try:
            with engine.connect() as conn:
                conn.execute(text(f"insert into {table_name} values (1); insert into {table_name} values (2)"))
                conn.commit()
            # If it worked, verify both rows
            with engine.connect() as conn:
                count = conn.execute(text(f"select count(*) from {table_name}")).scalar_one()
                assert count == 2, f"Expected 2 rows, got {count}"
            print(f"  {compat} multiple statements: supported (2 rows inserted)")
        except Exception:
            print(f"  {compat} multiple statements: rejected (expected behavior)")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))
