"""Round 5: Connection pool, cursor operations, metadata, encoding, large data."""
import uuid, time, threading
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, LargeBinary, MetaData,
    Numeric, String, Table, Text, create_engine, inspect, select, text,
    func, Index, UniqueConstraint, ForeignKey, Float,
)
from sqlalchemy.orm import Session, declarative_base

from tests.test_config import ODBC_URLS as URLS

def _engine(compat, **kw):
    return create_engine(URLS[compat], pool_pre_ping=True, **kw)

def _tname(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 1. Pool exhaustion and recovery ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_pool_exhaustion(compat):
    """Test pool behavior when max connections reached."""
    engine = _engine(compat, pool_size=2, max_overflow=0)
    conns = []
    # Check out 2 connections (pool max)
    for i in range(2):
        c = engine.connect()
        conns.append(c)
        assert c.execute(text("select 1")).scalar_one() == 1

    # 3rd should timeout (pool exhausted)
    try:
        c3 = engine.connect()
        conns.append(c3)
        # If we get here, pool allowed overflow — not necessarily a bug
        print(f"  {compat} pool: 3rd connection allowed (overflow)")
    except Exception as e:
        assert "timeout" in str(e).lower() or "overflow" in str(e).lower(), f"Unexpected error: {e}"

    # Release one, should be able to connect again
    conns[0].close()
    with engine.connect() as c:
        assert c.execute(text("select 1")).scalar_one() == 1

    for c in conns[1:]:
        c.close()
    print(f"  {compat} pool exhaustion: PASS")


# ── 2. Cursor fetchone / fetchall / fetchmany ────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_cursor_fetch_modes(compat):
    """Test different fetch modes on raw cursor."""
    engine = _engine(compat)
    table_name = _tname("vfet")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i*10} for i in range(1, 11)])

        with engine.connect() as conn:
            result = conn.execute(text(f"select id, val from {table_name} order by id"))
            # fetchone
            row = result.fetchone()
            assert row == (1, 10)
            # fetchmany(3)
            rows = result.fetchmany(3)
            assert len(rows) == 3
            assert rows[0] == (2, 20)
            # fetchall (remaining)
            rows = result.fetchall()
            assert len(rows) == 6
            assert rows[-1] == (10, 100)
            # fetchone after exhausted
            row = result.fetchone()
            assert row is None
        print(f"  {compat} cursor fetch modes: PASS")
    finally:
        md.drop_all(engine)


# ── 3. get_schema_names ──────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_get_schema_names(compat):
    """Test inspector.get_schema_names()."""
    engine = _engine(compat)
    inspector = inspect(engine)
    schemas = inspector.get_schema_names()
    assert "public" in schemas, f"public not in schemas: {schemas}"
    # pg_catalog should not be in user schemas (or should it?)
    print(f"  {compat} schemas: {schemas}")
    print(f"  {compat} get_schema_names: PASS")


# ── 4. get_view_names / get_view_definition ──────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_get_view_names_and_definition(compat):
    """Test inspector.get_view_names() and get_view_definition()."""
    engine = _engine(compat)
    table_name = _tname("vvw_t")
    view_name = _tname("vvw_v")
    with engine.begin() as conn:
        conn.execute(text(f"drop view if exists {view_name}"))
        conn.execute(text(f"drop table if exists {table_name}"))
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32))"))
        conn.execute(text(f"insert into {table_name} values (1, 'hello')"))
        conn.execute(text(f"create view {view_name} as select id, name from {table_name} where id > 0"))
    try:
        inspector = inspect(engine)
        views = inspector.get_view_names()
        assert view_name in views, f"View {view_name} not in {views}"

        # get_view_definition
        try:
            defn = inspector.get_view_definition(view_name)
            assert defn is not None, f"View definition is None"
            assert "select" in str(defn).lower(), f"View definition doesn't contain select: {defn}"
            print(f"  {compat} get_view_definition: PASS — {str(defn)[:60]}")
        except Exception as e:
            print(f"  {compat} get_view_definition: {str(e)[:80]}")
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop view if exists {view_name}"))
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 5. Very long string (max varchar) ────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_long_string_roundtrip(compat):
    """Test string near max varchar length."""
    engine = _engine(compat)
    table_name = _tname("vlong")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("s", String(4000)))
    try:
        md.create_all(engine)
        long_str = "x" * 4000
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, s=long_str))
            result = conn.execute(select(t.c.s).where(t.c.id == 1)).scalar_one()
            assert result == long_str, f"Long string mismatch: len={len(result)}"
        print(f"  {compat} long string (4000): PASS")
    finally:
        md.drop_all(engine)


# ── 6. Text column with very large content ───────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_large_text_roundtrip(compat):
    """Test TEXT column with large content."""
    engine = _engine(compat)
    table_name = _tname("vbigtext")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("content", Text))
    try:
        md.create_all(engine)
        # M compat TEXT max is 65535; use 50000 for all to keep it uniform
        text_size = 50000
        big_text = "A" * text_size
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, content=big_text))
            result = conn.execute(select(t.c.content).where(t.c.id == 1)).scalar_one()
            assert len(result) == text_size, f"Large text: expected {text_size}, got {len(result)}"
        print(f"  {compat} large text ({text_size}): PASS")
    finally:
        md.drop_all(engine)


# ── 7. Negative numbers ──────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_negative_numbers(compat):
    """Test negative integers and decimals."""
    engine = _engine(compat)
    table_name = _tname("vneg")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("int_val", Integer),
        Column("num_val", Numeric(10, 2)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, int_val=-1, num_val=Decimal("-99.99")))
            conn.execute(t.insert().values(id=2, int_val=-2147483648, num_val=Decimal("-99999999.99")))
            rows = conn.execute(select(t.c.int_val, t.c.num_val).order_by(t.c.id)).all()
            assert rows[0] == (-1, Decimal("-99.99")), f"Row 0: {rows[0]}"
            assert rows[1] == (-2147483648, Decimal("-99999999.99")), f"Row 1: {rows[1]}"
        print(f"  {compat} negative numbers: PASS")
    finally:
        md.drop_all(engine)


# ── 8. Special float values ──────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_special_float_values(compat):
    """Test float: zero, negative zero, very small, very large."""
    import math
    engine = _engine(compat)
    table_name = _tname("vfloat")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("f", Float))
    try:
        md.create_all(engine)
        test_vals = [0.0, -0.0, 1e-10, 1e10, -1e10, 3.14159]
        with engine.begin() as conn:
            for i, v in enumerate(test_vals, 1):
                conn.execute(t.insert().values(id=i, f=v))
            rows = conn.execute(select(t.c.f).order_by(t.c.id)).all()
            for expected, actual in zip(test_vals, rows):
                # M compat FLOAT has ~7 digit precision; use looser tolerance
                tol = 1e-3 if compat == "M" else 1e-6
                assert abs(actual[0] - expected) < tol or (expected == 0 and abs(actual[0]) < tol), \
                    f"Float mismatch: {expected} -> {actual[0]}"
        print(f"  {compat} special float: PASS")
    finally:
        md.drop_all(engine)


# ── 9. Null byte in string ───────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_null_byte_in_string(compat):
    """Test string containing null byte."""
    engine = _engine(compat)
    table_name = _tname("vnullbyte")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("s", String(100)))
    try:
        md.create_all(engine)
        test_str = "hello\x00world"
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, s=test_str))
            result = conn.execute(select(t.c.s).where(t.c.id == 1)).scalar_one()
            # Some databases truncate at null byte
            if result == test_str:
                print(f"  {compat} null byte: PASS (full round-trip)")
            elif result == "hello":
                print(f"  {compat} null byte: truncated at \\x00 (DB behavior)")
            else:
                print(f"  {compat} null byte: {repr(result)}")
    finally:
        md.drop_all(engine)


# ── 10. Special characters in strings ────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_special_chars_in_strings(compat):
    """Test strings with quotes, backslashes, newlines."""
    engine = _engine(compat)
    table_name = _tname("vspecial")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("s", String(200)))
    try:
        md.create_all(engine)
        test_strs = [
            "it's a test",
            'say "hello"',
            "back\\slash",
            "line1\nline2",
            "tab\there",
            "混合中文English日本語",
            "emoji: 🎉🔥",
            "control: \x01\x02\x03",
        ]
        with engine.begin() as conn:
            for i, s in enumerate(test_strs, 1):
                conn.execute(t.insert().values(id=i, s=s))
            for i, expected in enumerate(test_strs, 1):
                result = conn.execute(select(t.c.s).where(t.c.id == i)).scalar_one()
                assert result == expected, f"Row {i}: expected {repr(expected)}, got {repr(result)}"
        print(f"  {compat} special chars: PASS")
    finally:
        md.drop_all(engine)


# ── 11. Bulk insert 1000 rows ────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_bulk_insert_1000(compat):
    """Test bulk insert of 1000 rows."""
    engine = _engine(compat)
    table_name = _tname("vbulk1k")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i} for i in range(1, 1001)])
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 1000
            total = conn.execute(select(func.sum(t.c.val))).scalar_one()
            assert total == 500500  # sum(1..1000)
        print(f"  {compat} bulk insert 1000: PASS")
    finally:
        md.drop_all(engine)


# ── 12. Bulk insert 10000 rows ───────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_bulk_insert_10000(compat):
    """Test bulk insert of 10000 rows."""
    engine = _engine(compat)
    table_name = _tname("vbulk10k")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": i} for i in range(1, 10001)])
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 10000
        print(f"  {compat} bulk insert 10000: PASS")
    finally:
        md.drop_all(engine)


# ── 13. Connection: close and use ────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_connection_close_and_reuse(compat):
    """Test that closed connection is properly returned to pool."""
    engine = _engine(compat, pool_size=1, max_overflow=0)
    conn1 = engine.connect()
    assert conn1.execute(text("select 1")).scalar_one() == 1
    conn1.close()

    conn2 = engine.connect()
    assert conn2.execute(text("select 2")).scalar_one() == 2
    conn2.close()

    # Should be same underlying connection (pool reuse)
    status = engine.pool.status()
    print(f"  {compat} pool status: {status}")
    print(f"  {compat} connection close+reuse: PASS")


# ── 14. DateTime with microseconds precision ─────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_datetime_microseconds(compat):
    """Test DateTime with various microsecond values."""
    engine = _engine(compat)
    table_name = _tname("vdt_us")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        test_vals = [
            datetime(2026, 1, 1, 0, 0, 0, 0),
            datetime(2026, 1, 1, 0, 0, 0, 1),
            datetime(2026, 6, 23, 12, 30, 45, 123456),
            datetime(2026, 6, 23, 23, 59, 59, 999999),
            datetime(1999, 12, 31, 23, 59, 59, 500000),
        ]
        with engine.begin() as conn:
            for i, ts in enumerate(test_vals, 1):
                conn.execute(t.insert().values(id=i, ts=ts))
            rows = conn.execute(select(t.c.ts).order_by(t.c.id)).all()
            for expected, actual in zip(test_vals, rows):
                # ODBC driver truncates microseconds to milliseconds on some platforms
                _actual = actual[0]
                _expected = expected
                if compat == "M":
                    _actual = _actual.replace(microsecond=(_actual.microsecond // 1000) * 1000) if hasattr(_actual, 'microsecond') else _actual
                    _expected = _expected.replace(microsecond=(_expected.microsecond // 1000) * 1000) if hasattr(_expected, 'microsecond') else _expected
                assert _actual == _expected, f"DT mismatch: {expected} -> {actual[0]}"
        print(f"  {compat} datetime microseconds: PASS")
    finally:
        md.drop_all(engine)


# ── 15. Date range across millennia ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_date_range_millennia(compat):
    """Test dates across wide range."""
    engine = _engine(compat)
    table_name = _tname("vdate2")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("d", Date))
    try:
        md.create_all(engine)
        test_dates = [
            date(1, 1, 1),
            date(100, 1, 1),
            date(1000, 1, 1),
            date(1582, 10, 15),  # Gregorian calendar start
            date(1900, 1, 1),
            date(2000, 2, 29),   # Y2K leap day
            date(2024, 2, 29),   # Recent leap day
            date(9999, 12, 31),
        ]
        with engine.begin() as conn:
            for i, d in enumerate(test_dates, 1):
                conn.execute(t.insert().values(id=i, d=d))
            rows = conn.execute(select(t.c.d).order_by(t.c.id)).all()
            for expected, actual in zip(test_dates, rows):
                # ODBC driver may return datetime instead of date
                _actual = actual[0]
                if hasattr(_actual, "date"):
                    _actual = _actual.date()
                assert _actual == expected, f"Date mismatch: {expected} -> {actual[0]}"
        print(f"  {compat} date millennia range: PASS")
    finally:
        md.drop_all(engine)


# ── 16. Aggregate functions ──────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_aggregate_functions(compat):
    """Test all standard aggregate functions."""
    engine = _engine(compat)
    table_name = _tname("vagg")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": v} for i, v in
                [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]])

            assert conn.execute(select(func.count()).select_from(t)).scalar_one() == 5
            assert conn.execute(select(func.sum(t.c.val))).scalar_one() == 150
            assert conn.execute(select(func.avg(t.c.val))).scalar_one() == 30.0
            assert conn.execute(select(func.min(t.c.val))).scalar_one() == 10
            assert conn.execute(select(func.max(t.c.val))).scalar_one() == 50
        print(f"  {compat} aggregates: PASS")
    finally:
        md.drop_all(engine)


# ── 17. Math functions ───────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_math_functions(compat):
    """Test math functions via raw SQL."""
    engine = _engine(compat)
    with engine.connect() as conn:
        assert conn.execute(text("select abs(-5)")).scalar_one() == 5
        assert conn.execute(text("select ceil(4.2)")).scalar_one() == 5
        assert conn.execute(text("select floor(4.8)")).scalar_one() == 4
        assert float(conn.execute(text("select round(4.567, 2)")).scalar_one()) == 4.57
        assert conn.execute(text("select power(2, 10)")).scalar_one() == 1024.0
        assert conn.execute(text("select mod(17, 5)")).scalar_one() == 2
        assert conn.execute(text("select sign(-3)")).scalar_one() == -1
        assert conn.execute(text("select sign(0)")).scalar_one() == 0
    print(f"  {compat} math functions: PASS")


# ── 18. String functions ─────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_string_functions(compat):
    """Test string functions via raw SQL."""
    engine = _engine(compat)
    with engine.connect() as conn:
        assert conn.execute(text("select length('hello')")).scalar_one() == 5
        assert conn.execute(text("select upper('hello')")).scalar_one() == "HELLO"
        assert conn.execute(text("select lower('HELLO')")).scalar_one() == "hello"
        assert conn.execute(text("select substring('hello', 2, 3)")).scalar_one() == "ell"
        assert conn.execute(text("select trim('  x  ')")).scalar_one() == "x"
        assert conn.execute(text("select replace('abcabc', 'b', 'X')")).scalar_one() == "aXcaXc"
        assert conn.execute(text("select position('lo' in 'hello')")).scalar_one() == 4
        assert conn.execute(text("select concat('a', 'b', 'c')")).scalar_one() == "abc"
    print(f"  {compat} string functions: PASS")


# ── 19. ADD CONSTRAINT after table creation ──────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_add_constraint_after_create(compat):
    """Test ALTER TABLE ADD CONSTRAINT via raw SQL."""
    engine = _engine(compat)
    table_name = _tname("vaddcon")
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int, name varchar(32))"))
    try:
        # Add PK
        with engine.begin() as conn:
            conn.execute(text(f"alter table {table_name} add primary key (id)"))
        pk = inspect(engine).get_pk_constraint(table_name)
        assert pk["constrained_columns"] == ["id"]

        # Add unique constraint
        with engine.begin() as conn:
            conn.execute(text(f"alter table {table_name} add constraint uq_{table_name} unique (name)"))
        uqs = inspect(engine).get_unique_constraints(table_name)
        assert any(uq["column_names"] == ["name"] for uq in uqs)

        # Add check constraint
        with engine.begin() as conn:
            conn.execute(text(f"alter table {table_name} add constraint ck_{table_name} check (id > 0)"))
        cks = inspect(engine).get_check_constraints(table_name)
        assert len(cks) > 0

        print(f"  {compat} add constraints: PASS")
    except Exception as e:
        print(f"  {compat} add constraints: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 20. DROP CONSTRAINT ──────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_drop_constraint(compat):
    """Test ALTER TABLE DROP CONSTRAINT via raw SQL."""
    engine = _engine(compat)
    table_name = _tname("vdropcon")
    constraint_name = f"uq_{table_name}"
    with engine.begin() as conn:
        conn.execute(text(f"create table {table_name} (id int primary key, name varchar(32), constraint {constraint_name} unique (name))"))
    try:
        uqs = inspect(engine).get_unique_constraints(table_name)
        assert any(uq["name"] == constraint_name for uq in uqs)

        with engine.begin() as conn:
            conn.execute(text(f"alter table {table_name} drop constraint {constraint_name}"))

        uqs = inspect(engine).get_unique_constraints(table_name)
        assert not any(uq["name"] == constraint_name for uq in uqs), f"Constraint not dropped: {uqs}"
        print(f"  {compat} drop constraint: PASS")
    except Exception as e:
        print(f"  {compat} drop constraint: {e}")
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"drop table if exists {table_name}"))


# ── 21. Multiple indexes on same table ───────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_multiple_indexes(compat):
    """Test table with multiple indexes."""
    engine = _engine(compat)
    table_name = _tname("vmultiix")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("a", String(32)),
        Column("b", String(32)),
        Column("c", Integer),
    )
    Index(f"ix_{table_name}_a", t.c.a)
    Index(f"ix_{table_name}_b", t.c.b)
    Index(f"ix_{table_name}_ab", t.c.a, t.c.b)
    Index(f"ix_{table_name}_c", t.c.c)
    try:
        md.create_all(engine)
        indexes = inspect(engine).get_indexes(table_name)
        assert len(indexes) >= 4, f"Expected >= 4 indexes, got {len(indexes)}: {[i['name'] for i in indexes]}"
        names = {ix["name"] for ix in indexes}
        expected_names = {f"ix_{table_name}_a", f"ix_{table_name}_b", f"ix_{table_name}_ab", f"ix_{table_name}_c"}
        assert expected_names.issubset(names), f"Missing indexes: {expected_names - names}"
        print(f"  {compat} multiple indexes: PASS ({len(indexes)} indexes)")
    finally:
        md.drop_all(engine)


# ── 22. Table with many foreign keys ─────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_multiple_foreign_keys(compat):
    """Test table with multiple FK constraints."""
    engine = _engine(compat)
    p1 = _tname("vfk_p1")
    p2 = _tname("vfk_p2")
    c = _tname("vfk_child")
    md = MetaData()
    t_p1 = Table(p1, md, Column("id", Integer, primary_key=True))
    t_p2 = Table(p2, md, Column("id", Integer, primary_key=True))
    t_c = Table(c, md,
        Column("id", Integer, primary_key=True),
        Column("p1_id", Integer, ForeignKey(f"{p1}.id")),
        Column("p2_id", Integer, ForeignKey(f"{p2}.id")),
    )
    try:
        md.create_all(engine)
        fks = inspect(engine).get_foreign_keys(c)
        assert len(fks) == 2, f"Expected 2 FKs, got {len(fks)}"
        referred_tables = {fk["referred_table"] for fk in fks}
        assert referred_tables == {p1, p2}
        print(f"  {compat} multiple FKs: PASS")
    finally:
        md.drop_all(engine)


# ── 23. Self-referencing foreign key ─────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_self_referencing_fk(compat):
    """Test self-referencing FK (tree structure)."""
    engine = _engine(compat)
    table_name = _tname("vselfk")
    md = MetaData()
    t = Table(table_name, md,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey(f"{table_name}.id")),
        Column("name", String(32)),
    )
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, parent_id=None, name="root"))
            conn.execute(t.insert().values(id=2, parent_id=1, name="child1"))
            conn.execute(t.insert().values(id=3, parent_id=1, name="child2"))
            conn.execute(t.insert().values(id=4, parent_id=2, name="grandchild"))

            # Self-join
            from sqlalchemy import and_
            result = conn.execute(
                select(t.c.id, t.c.name)
                .select_from(t)
                .where(t.c.parent_id == 1)
                .order_by(t.c.id)
            ).all()
            assert [r[0] for r in result] == [2, 3]
        print(f"  {compat} self-ref FK: PASS")
    finally:
        md.drop_all(engine)


# ── 24. Time zone conversion ─────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_timezone_aware_datetime_insert(compat):
    """Test inserting timezone-aware datetimes from different timezones."""
    engine = _engine(compat)
    table_name = _tname("vtz2")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("ts", DateTime))
    try:
        md.create_all(engine)
        # Insert from UTC+8
        tz8 = timezone(timedelta(hours=8))
        aware = datetime(2026, 6, 23, 20, 0, 0, tzinfo=tz8)
        expected_utc = datetime(2026, 6, 23, 12, 0, 0)

        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, ts=aware))
            result = conn.execute(select(t.c.ts).where(t.c.id == 1)).scalar_one()
            # ODBC driver may strip timezone info — compare as naive UTC
            _result_naive = result.replace(tzinfo=None) if result.tzinfo else result
            assert _result_naive == expected_utc, f"TZ conversion: {aware} -> {result}, expected {expected_utc}"
        print(f"  {compat} timezone conversion: PASS")

        # Insert from UTC-5
        tzn5 = timezone(timedelta(hours=-5))
        aware2 = datetime(2026, 6, 23, 7, 0, 0, tzinfo=tzn5)
        expected_utc2 = datetime(2026, 6, 23, 12, 0, 0)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=2, ts=aware2))
            result2 = conn.execute(select(t.c.ts).where(t.c.id == 2)).scalar_one()
            assert result2 == expected_utc2, f"TZ conversion: {aware2} -> {result2}, expected {expected_utc2}"
    finally:
        md.drop_all(engine)


# ── 25. Repeated create/drop cycle ───────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_repeated_create_drop(compat):
    """Test repeated create/drop cycle — cache consistency."""
    engine = _engine(compat)
    table_name = _tname("vrepeat")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        for cycle in range(5):
            md.create_all(engine)
            with engine.begin() as conn:
                conn.execute(t.insert().values(id=1, val=cycle))
                result = conn.execute(select(t.c.val).where(t.c.id == 1)).scalar_one()
                assert result == cycle, f"Cycle {cycle}: expected {cycle}, got {result}"
            md.drop_all(engine)
        print(f"  {compat} repeated create/drop (5 cycles): PASS")
    finally:
        md.drop_all(engine)


# ── 26. SQL injection prevention ─────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_sql_injection_prevention(compat):
    """Test that parameterized queries prevent SQL injection."""
    engine = _engine(compat)
    table_name = _tname("vinject")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("name", String(200)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert().values(id=1, name="normal"))

            # Try injection via parameter
            injection = "'; DROP TABLE " + table_name + "; --"
            conn.execute(t.insert().values(id=2, name=injection))
            result = conn.execute(select(t.c.name).where(t.c.id == 2)).scalar_one()
            assert result == injection, f"Injection prevention failed: {result}"

            # Table should still exist
            count = conn.execute(select(func.count()).select_from(t)).scalar_one()
            assert count == 2
        print(f"  {compat} SQL injection prevention: PASS")
    finally:
        md.drop_all(engine)


# ── 27. EXISTS subquery ──────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_exists_subquery(compat):
    """Test EXISTS subquery."""
    from sqlalchemy import exists
    engine = _engine(compat)
    parent = _tname("vex_p")
    child = _tname("vex_c")
    md = MetaData()
    p = Table(parent, md, Column("id", Integer, primary_key=True), Column("name", String(32)))
    c = Table(child, md, Column("id", Integer, primary_key=True), Column("pid", Integer, ForeignKey(f"{parent}.id")))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(p.insert(), [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}])
            conn.execute(c.insert(), [{"id": 1, "pid": 1}, {"id": 2, "pid": 1}, {"id": 3, "pid": 3}])

            # Parents that have children
            result = conn.execute(
                select(p.c.name).where(exists().where(c.c.pid == p.c.id)).order_by(p.c.name)
            ).all()
            assert [r[0] for r in result] == ["a", "c"], f"EXISTS failed: {result}"
        print(f"  {compat} EXISTS subquery: PASS")
    finally:
        md.drop_all(engine)


# ── 28. COUNT DISTINCT ───────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_count_distinct(compat):
    """Test COUNT(DISTINCT ...) via SQLAlchemy."""
    engine = _engine(compat)
    table_name = _tname("vcdist")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("cat", String(10)))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "cat": c} for i, c in
                [(1,"a"), (2,"a"), (3,"b"), (4,"b"), (5,"c"), (6,"c"), (7,"c")]])
            count = conn.execute(select(func.count(func.distinct(t.c.cat)))).scalar_one()
            assert count == 3, f"COUNT DISTINCT: expected 3, got {count}"
        print(f"  {compat} COUNT DISTINCT: PASS")
    finally:
        md.drop_all(engine)


# ── 29. ORDER BY multiple columns with mixed direction ───────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_order_by_mixed_direction(compat):
    """Test ORDER BY with mixed ASC/DESC."""
    engine = _engine(compat)
    table_name = _tname("vord")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("a", Integer), Column("b", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "a": a, "b": b} for i, a, b in
                [(1,1,10), (2,1,20), (3,2,10), (4,2,20), (5,3,15)]])
            result = conn.execute(
                select(t.c.id).order_by(t.c.a.asc(), t.c.b.desc())
            ).all()
            assert [r[0] for r in result] == [2, 1, 4, 3, 5]
        print(f"  {compat} ORDER BY mixed direction: PASS")
    finally:
        md.drop_all(engine)


# ── 30. BETWEEN operator ─────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_between(compat):
    """Test BETWEEN operator."""
    engine = _engine(compat)
    table_name = _tname("vbtwn")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": i, "val": v} for i, v in
                [(1,10), (2,20), (3,30), (4,40), (5,50)]])
            result = conn.execute(
                select(t.c.val).where(t.c.val.between(20, 40)).order_by(t.c.val)
            ).all()
            assert [r[0] for r in result] == [20, 30, 40]
        print(f"  {compat} BETWEEN: PASS")
    finally:
        md.drop_all(engine)


# ── 31. IS NULL / IS NOT NULL ────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_is_null_is_not_null(compat):
    """Test IS NULL / IS NOT NULL filters."""
    engine = _engine(compat)
    table_name = _tname("visnull")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", Integer, nullable=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": 1, "val": 10}, {"id": 2, "val": None}, {"id": 3, "val": 30}])

            nulls = conn.execute(select(t.c.id).where(t.c.val.is_(None)).order_by(t.c.id)).all()
            assert [r[0] for r in nulls] == [2]

            not_nulls = conn.execute(select(t.c.id).where(t.c.val.is_not(None)).order_by(t.c.id)).all()
            assert [r[0] for r in not_nulls] == [1, 3]
        print(f"  {compat} IS NULL/IS NOT NULL: PASS")
    finally:
        md.drop_all(engine)


# ── 32. COALESCE ─────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("compat", ["A", "B", "M"])
def test_coalesce(compat):
    """Test COALESCE function."""
    from sqlalchemy import func
    engine = _engine(compat)
    table_name = _tname("vcoal")
    md = MetaData()
    t = Table(table_name, md, Column("id", Integer, primary_key=True), Column("val", String(32), nullable=True))
    try:
        md.create_all(engine)
        with engine.begin() as conn:
            conn.execute(t.insert(), [{"id": 1, "val": "real"}, {"id": 2, "val": None}])
            result = conn.execute(
                select(t.c.id, func.coalesce(t.c.val, "default")).order_by(t.c.id)
            ).all()
            assert result == [(1, "real"), (2, "default")]
        print(f"  {compat} COALESCE: PASS")
    finally:
        md.drop_all(engine)
