"""FN04 — concurrent invoice creation must not bill one sales order twice.

Two entry points can create an invoice for the same sales order:

* ``POST /finance/invoices``                 -> ``finance.create_invoice``
* ``POST /sales-orders/{sid}/generate-invoice`` -> ``sales.generate_invoice_for_order``

Both used to load the sales order with an *unlocked* ``db.get(...)`` and only
then ask "does an invoice already exist?".  Two concurrent requests could both
observe "no invoice yet" and both insert one, billing the same order twice.

Concurrency evidence requires real row-level locking, so the race tests below
run against a real PostgreSQL server using two independent connections.
SQLite silently ignores ``FOR UPDATE``/``FOR NO KEY UPDATE``; a green SQLite run
only proves the non-concurrent paths still work and proves nothing about the
race itself.
"""
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import finance as finance_routes
from app.api.routes import sales as sales_routes
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Invoice, SalesOrder, User
from app.schemas.sales import InvoiceIn

import app.models  # noqa: F401  — registers every table on Base.metadata


# --------------------------------------------------------------------------
# Non-concurrent behaviour (SQLite suite) — these guard the paths the fix
# must leave untouched.
# --------------------------------------------------------------------------

def _make_order(status: str = "confirmed", total: float = 500.0) -> int:
    with SessionLocal() as db:
        so = SalesOrder(
            order_no=f"FN04-{uuid.uuid4().hex[:10]}",
            status=status,
            total_amount=total,
        )
        db.add(so)
        db.commit()
        return so.id


def test_finance_invoice_404_for_missing_order(client, auth_headers):
    r = client.post(
        "/api/finance/invoices",
        headers=auth_headers,
        json={"sales_order_id": 999_999_999},
    )
    assert r.status_code == 404, r.text


def test_sales_generate_invoice_404_for_missing_order(client, auth_headers):
    r = client.post("/api/sales-orders/999999999/generate-invoice", headers=auth_headers)
    assert r.status_code == 404, r.text


def test_sales_generate_invoice_rejects_disallowed_status(client, auth_headers):
    sid = _make_order(status="draft")
    r = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert r.status_code == 400, r.text
    assert "Cannot generate invoice" in r.text
    with SessionLocal() as db:
        assert db.query(Invoice).filter(Invoice.sales_order_id == sid).count() == 0


def test_second_call_returns_existing_invoice_on_both_entry_points(client, auth_headers):
    """Sequential (non-concurrent) double call must not create a second row."""
    sid = _make_order()

    first = client.post("/api/finance/invoices", headers=auth_headers, json={"sales_order_id": sid})
    assert first.status_code == 201, first.text
    created = first.json()

    again = client.post("/api/finance/invoices", headers=auth_headers, json={"sales_order_id": sid})
    assert again.status_code == 201, again.text
    assert again.json()["id"] == created["id"]
    assert again.json()["invoice_no"] == created["invoice_no"]

    # The other entry point must agree with the first one.
    via_sales = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert via_sales.status_code == 200, via_sales.text
    assert via_sales.json()["id"] == created["id"]
    assert via_sales.json()["created_existing"] is True

    with SessionLocal() as db:
        rows = db.query(Invoice).filter(Invoice.sales_order_id == sid).all()
        assert len(rows) == 1
        assert rows[0].invoice_no == created["invoice_no"]


def test_sales_first_then_finance_agrees(client, auth_headers):
    sid = _make_order()
    created = client.post(f"/api/sales-orders/{sid}/generate-invoice", headers=auth_headers)
    assert created.status_code == 200, created.text
    assert created.json()["created_existing"] is False

    via_finance = client.post("/api/finance/invoices", headers=auth_headers, json={"sales_order_id": sid})
    assert via_finance.status_code == 201, via_finance.text
    assert via_finance.json()["id"] == created.json()["id"]

    with SessionLocal() as db:
        assert db.query(Invoice).filter(Invoice.sales_order_id == sid).count() == 1


# --------------------------------------------------------------------------
# Concurrency — real PostgreSQL, two independent connections.
# --------------------------------------------------------------------------

_PG_ADMIN_URL = os.environ.get(
    "FN04_TEST_PG_ADMIN_URL", "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/postgres"
)
_GATE_TIMEOUT = 30.0        # how long we hold the first caller's commit open
_SECOND_CALLER_WAIT = 2.0  # grace period for the second caller to race in


def _pg_reachable() -> bool:
    try:
        eng = create_engine(_PG_ADMIN_URL, connect_args={"connect_timeout": 5}, future=True)
        try:
            with eng.connect() as conn:
                conn.execute(text("select 1"))
        finally:
            eng.dispose()
        return True
    except Exception:
        return False


_pg_unavailable = (
    "PostgreSQL is required for the FN04 concurrency proof (SQLite does not implement "
    "FOR NO KEY UPDATE). Set FN04_TEST_PG_ADMIN_URL to a reachable admin DSN."
)


@pytest.fixture(scope="module")
def pg_sessionmaker():
    if not _pg_reachable():
        pytest.skip(_pg_unavailable)

    import psycopg2

    name = "fn04_test_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(_PG_ADMIN_URL.replace("postgresql+psycopg2://", "postgresql://"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'create database "{name}"')
    admin.close()

    engine = create_engine(_PG_ADMIN_URL.rsplit("/", 1)[0] + "/" + name, future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    try:
        yield maker
    finally:
        engine.dispose()
        admin = psycopg2.connect(_PG_ADMIN_URL.replace("postgresql+psycopg2://", "postgresql://"))
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f'drop database if exists "{name}" with (force)')
        admin.close()


class _GatedSession(Session):
    """Session whose ``commit()`` parks until released.

    This holds the first caller's transaction open — invoice inserted but not
    yet visible to anybody — so the second caller genuinely runs against a
    "no invoice yet" world.  The route code itself is untouched.
    """

    def __init__(self, *args, gate=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._gate = gate
        self.at_commit_gate = threading.Event()

    def commit(self):
        if self._gate is not None:
            self.at_commit_gate.set()
            if not self._gate.wait(timeout=_GATE_TIMEOUT):
                raise AssertionError("first caller's commit gate was never released")
        return super().commit()


@pytest.fixture
def pg_order(pg_sessionmaker):
    """A confirmed sales order plus a user, inside the throwaway PG database."""
    with pg_sessionmaker() as db:
        user = User(
            name="FN04 Tester",
            email=f"fn04-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-used",
        )
        db.add(user)
        db.flush()
        order = SalesOrder(
            order_no=f"FN04-PG-{uuid.uuid4().hex[:10]}",
            status="confirmed",
            total_amount=750.0,
        )
        db.add(order)
        db.commit()
        return order.id, user.id


def _call_entry_point(entry, db, order_id, user_id):
    """Invoke the real route function with the real session."""
    user = db.get(User, user_id)
    if entry == "finance":
        return finance_routes.create_invoice(InvoiceIn(sales_order_id=order_id), db, user)
    return sales_routes.generate_invoice_for_order(order_id, db, user)


def _identity(result):
    if isinstance(result, dict):
        return result["id"], result["invoice_no"], result.get("created_existing")
    return result.id, result.invoice_no, None


def _race(pg_sessionmaker, order_id, user_id, first_entry, second_entry):
    """Run two concurrent invoice creations for one order.

    The first caller's commit is held open, so the second caller starts while
    the first invoice is still uncommitted and invisible.
    """
    release = threading.Event()
    results, errors = {}, {}

    def call(entry, db, key):
        try:
            results[key] = _call_entry_point(entry, db, order_id, user_id)
        except BaseException as exc:  # noqa: BLE001 - surfaced in the assertion
            errors[key] = exc

    bind = pg_sessionmaker.kw["bind"]
    db_first = _GatedSession(bind=bind, gate=release, expire_on_commit=False, future=True)
    db_second = pg_sessionmaker()

    try:
        t_first = threading.Thread(target=call, args=(first_entry, db_first, "first"))
        t_first.start()
        assert db_first.at_commit_gate.wait(timeout=_GATE_TIMEOUT), (
            f"{first_entry} caller never reached its commit gate (errors={errors!r})"
        )

        t_second = threading.Thread(target=call, args=(second_entry, db_second, "second"))
        t_second.start()
        # Give the second caller time to race into the window.
        second_finished_early = t_second.join(timeout=_SECOND_CALLER_WAIT)

        release.set()
        t_first.join(timeout=_GATE_TIMEOUT)
        t_second.join(timeout=_GATE_TIMEOUT)
    finally:
        release.set()
        db_first.close()
        db_second.close()

    return results, errors, second_finished_early


@pytest.mark.parametrize("entry", ["finance", "sales"])
def test_concurrent_same_entry_point_creates_exactly_one_invoice(pg_sessionmaker, pg_order, entry):
    order_id, user_id = pg_order
    results, errors, finished_early = _race(pg_sessionmaker, order_id, user_id, entry, entry)

    with pg_sessionmaker() as db:
        invoices = db.query(Invoice).filter(Invoice.sales_order_id == order_id).all()

    assert not errors, f"{entry} race raised: {errors!r}"
    assert len(invoices) == 1, (
        f"FN04: {entry} double-billed order {order_id} — {len(invoices)} invoices "
        f"created ({[i.invoice_no for i in invoices]}); second caller finished "
        f"before release={finished_early}; results={ {k: _identity(v) for k, v in results.items()} }"
    )

    winner, loser = _identity(results["first"]), _identity(results["second"])
    assert winner[0] == loser[0], f"callers disagreed on the invoice: {winner} vs {loser}"
    assert winner[1] == loser[1]
    if entry == "sales":
        # Whoever did not create the row must be told it already existed.
        assert {winner[2], loser[2]} == {True, False}


def test_concurrent_mixed_entry_points_create_exactly_one_invoice(pg_sessionmaker, pg_order):
    order_id, user_id = pg_order
    results, errors, finished_early = _race(pg_sessionmaker, order_id, user_id, "finance", "sales")

    with pg_sessionmaker() as db:
        invoices = db.query(Invoice).filter(Invoice.sales_order_id == order_id).all()

    assert not errors, f"mixed race raised: {errors!r}"
    assert len(invoices) == 1, (
        f"FN04: finance+sales double-billed order {order_id} — {len(invoices)} invoices "
        f"({[i.invoice_no for i in invoices]}); second finished before release={finished_early}"
    )
    first, second = _identity(results["first"]), _identity(results["second"])
    assert first[0] == second[0], f"entry points disagreed: {first} vs {second}"
    assert first[1] == second[1]


def test_concurrent_creation_does_not_duplicate_invoice_numbers(pg_sessionmaker, pg_order):
    order_id, user_id = pg_order
    results, errors, _ = _race(pg_sessionmaker, order_id, user_id, "finance", "sales")
    assert not errors, f"race raised: {errors!r}"

    with pg_sessionmaker() as db:
        numbers = [row[0] for row in db.query(Invoice.invoice_no).all()]
    assert len(numbers) == len(set(numbers)), f"duplicate invoice_no consumed: {numbers}"
