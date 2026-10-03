"""FN07-INVOICE — invoice/payment money inputs must be storage-bounded.

`invoices.amount` and `payments.amount` are both ``Numeric(14, 2)`` and carry
``amount >= 0`` / ``amount > 0`` check constraints.  ``InvoiceIn.amount`` and
``PaymentIn.amount`` were unbounded Python ``float`` fields, so a client could
send ``Infinity``, ``NaN``, a sub-cent value, or a magnitude far past the
column.  Downstream that value reaches ``Decimal(str(value))`` in
``app.services.payments.money_decimal`` and the invoice/payment INSERT.

What the raw numbers mean before the fix:

* ``inf`` / ``NaN``  — accepted by the schema, poison every later Decimal
  conversion and any money aggregation.
* sub-cent           — the column silently rounds, so a caller-visible amount
  is not the amount that gets billed.
* overflow           — PostgreSQL raises ``NumericValueOutOfRange`` at INSERT
  time, i.e. *after* the row/audit work has begun, instead of a clean 422.

The tests below pin the HTTP contract (SQLite suite), the schema contract, and
the "reject before any write" guarantee.  SQLite does not enforce ``NUMERIC``
precision, so the storage-bound proof runs against a real PostgreSQL server via
``STABILIZATION_POSTGRES_URL``; when that variable is unset those tests SKIP.
"""
import inspect
import os
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from app.api.routes import finance as finance_routes
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Invoice, Payment, SalesOrder, User
from app.schemas.sales import InvoiceIn, PaymentIn

import app.models  # noqa: F401  — registers every table on Base.metadata


# `Numeric(14, 2)` stores at most 14 significant digits with 2 decimal places.
MAX_STORED_MONEY = Decimal("999999999999.99")
OVERFLOW_MONEY = Decimal("1000000000000.00")  # one cent past the column
SUBCENT_MONEY = Decimal("0.001")
CENT_MONEY = Decimal("0.01")

# Amounts a client can express but the column cannot hold.
INVOICE_BAD_AMOUNTS = [
    pytest.param(float("inf"), id="infinite"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float(SUBCENT_MONEY), id="sub-cent"),
    pytest.param(float(OVERFLOW_MONEY), id="column-overflow"),
    pytest.param(1e300, id="grossly-out-of-range"),
    pytest.param(-5.0, id="negative"),
]

PAYMENT_BAD_AMOUNTS = [
    pytest.param(float("inf"), id="infinite"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float(SUBCENT_MONEY), id="sub-cent"),
    pytest.param(float(OVERFLOW_MONEY), id="column-overflow"),
    pytest.param(1e300, id="grossly-out-of-range"),
    pytest.param(0.0, id="zero-violates-positive-check"),
    pytest.param(-5.0, id="negative"),
]


def _make_order(total: float = 500.0, status: str = "confirmed") -> int:
    with SessionLocal() as db:
        so = SalesOrder(
            order_no=f"FN07-{uuid.uuid4().hex[:10]}",
            status=status,
            total_amount=total,
        )
        db.add(so)
        db.commit()
        return int(so.id)


def _make_invoice(amount: float = 500.0) -> int:
    """A committed invoice, so payment tests start from a real ledger row."""
    with SessionLocal() as db:
        inv = Invoice(
            sales_order_id=_make_order(total=amount),
            invoice_no=f"FN07-INV-{uuid.uuid4().hex[:10]}",
            amount=amount,
            status="unpaid",
        )
        db.add(inv)
        db.commit()
        return int(inv.id)


def _counts(entity_type: str) -> tuple[int, int]:
    """(rows of that entity, audit rows for that entity)."""
    entity = {"Invoice": Invoice, "Payment": Payment}[entity_type]
    with SessionLocal() as db:
        return (
            db.query(entity).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == entity_type).count(),
        )


def _post_invoice(client, auth_headers, order_id: int, amount=...):
    body: dict = {"sales_order_id": order_id}
    if amount is not ...:
        body["amount"] = amount
    return client.post("/api/finance/invoices", headers=auth_headers, json=body)


@pytest.fixture
def lenient_client():
    """Returns 5xx responses instead of re-raising them.

    The default `TestClient` re-raises server errors, which hides whether a
    nonfinite amount produced a clean 422 or a 500 from a failed error render.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# Invoice write path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("amount", INVOICE_BAD_AMOUNTS)
def test_invoice_rejects_unrepresentable_amount(client, auth_headers, amount):
    order_id = _make_order()
    r = _post_invoice(client, auth_headers, order_id, amount)
    assert r.status_code == 422, f"accepted {amount!r}: {r.text}"


def test_invoice_accepts_maximum_stored_amount(client, auth_headers):
    order_id = _make_order()
    r = _post_invoice(client, auth_headers, order_id, float(MAX_STORED_MONEY))
    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["amount"])) == MAX_STORED_MONEY


def test_invoice_accepts_zero_amount(client, auth_headers):
    """`ck_invoices_amount_nonnegative` allows 0; the bound must allow it too."""
    order_id = _make_order()
    r = _post_invoice(client, auth_headers, order_id, 0.0)
    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["amount"])) == 0


def test_invoice_rejects_sub_cent_amount_without_writing_invoice_or_audit_row(client, auth_headers):
    order_id = _make_order()
    before = _counts("Invoice")
    r = _post_invoice(client, auth_headers, order_id, float(SUBCENT_MONEY))
    assert r.status_code == 422, r.text
    assert _counts("Invoice") == before, "a rejected amount left an invoice/audit row behind"


def test_invoice_rejects_overflow_without_writing_invoice_or_audit_row(client, auth_headers):
    order_id = _make_order()
    before = _counts("Invoice")
    r = _post_invoice(client, auth_headers, order_id, float(OVERFLOW_MONEY))
    assert r.status_code == 422, r.text
    assert _counts("Invoice") == before, "a rejected amount left an invoice/audit row behind"


# --------------------------------------------------------------------------
# Payment write path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("amount", PAYMENT_BAD_AMOUNTS)
def test_payment_rejects_unrepresentable_amount(client, auth_headers, amount):
    invoice_id = _make_invoice()
    r = client.post(
        "/api/finance/payments",
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": amount},
    )
    assert r.status_code == 422, f"accepted {amount!r}: {r.text}"


def test_payment_accepts_one_cent(client, auth_headers):
    invoice_id = _make_invoice()
    r = client.post(
        "/api/finance/payments",
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": float(CENT_MONEY)},
    )
    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["amount"])) == CENT_MONEY


def test_payment_rejects_sub_cent_without_writing_payment_or_audit_row(client, auth_headers):
    invoice_id = _make_invoice()
    before = _counts("Payment")
    r = client.post(
        "/api/finance/payments",
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": float(SUBCENT_MONEY)},
    )
    assert r.status_code == 422, r.text
    assert _counts("Payment") == before, "a rejected amount left a payment/audit row behind"


# --------------------------------------------------------------------------
# Nonfinite values must be a clean 422, not a 500 from a failed error render
# --------------------------------------------------------------------------

@pytest.mark.parametrize("amount", [float("inf"), float("nan")], ids=["infinite", "nan"])
def test_nonfinite_invoice_amount_returns_422_with_a_serializable_body(lenient_client, auth_headers, amount):
    order_id = _make_order()
    r = _post_invoice(lenient_client, auth_headers, order_id, amount)
    assert r.status_code == 422, f"{amount!r} produced {r.status_code}: {r.text[:200]}"
    assert r.json()["detail"], "the 422 body must still describe the rejected field"


@pytest.mark.parametrize("amount", [float("inf"), float("nan")], ids=["infinite", "nan"])
def test_nonfinite_payment_amount_returns_422_with_a_serializable_body(lenient_client, auth_headers, amount):
    invoice_id = _make_invoice()
    r = lenient_client.post(
        "/api/finance/payments",
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": amount},
    )
    assert r.status_code == 422, f"{amount!r} produced {r.status_code}: {r.text[:200]}"
    assert r.json()["detail"], "the 422 body must still describe the rejected field"


# --------------------------------------------------------------------------
# Server-side fallback: `amount` omitted falls back to `sales_orders.total_amount`
# --------------------------------------------------------------------------

def test_invoice_falls_back_to_bounded_sales_order_total(client, auth_headers):
    order_id = _make_order(total=123.45)
    r = _post_invoice(client, auth_headers, order_id)
    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["amount"])) == Decimal("123.45")


def test_storable_money_guard_rejects_unrepresentable_values():
    """Direct contract check for the guard the fallback path relies on.

    The ORM read path already normalises `sales_orders.total_amount` to the
    `NUMERIC(14, 2)` scale, so a sub-cent or oversized stored total is not
    reachable through `db.query(...)`. The guard still has to hold the line if
    that column is ever widened, re-typed, or fed by a raw SQL writer.
    """
    from app.api.routes.finance import _storable_invoice_amount

    for bad in (SUBCENT_MONEY, OVERFLOW_MONEY, Decimal("Infinity"), Decimal("NaN"), Decimal("-1")):
        with pytest.raises(HTTPException) as excinfo:
            _storable_invoice_amount(bad)
        assert excinfo.value.status_code == 422, f"accepted {bad!r}"
    assert _storable_invoice_amount(None) == 0
    assert _storable_invoice_amount(MAX_STORED_MONEY) == MAX_STORED_MONEY
    assert _storable_invoice_amount(Decimal("123.45")) == Decimal("123.45")


# --------------------------------------------------------------------------
# Schema contract — the bound lives in the type, not in per-route arithmetic
# --------------------------------------------------------------------------

def test_invoice_schema_rejects_nonfinite_and_unbounded_amounts():
    for bad in ("Infinity", "NaN", "-Infinity"):
        with pytest.raises(ValidationError):
            InvoiceIn(sales_order_id=1, amount=bad)
    with pytest.raises(ValidationError):
        InvoiceIn(sales_order_id=1, amount=float(OVERFLOW_MONEY))
    with pytest.raises(ValidationError):
        InvoiceIn(sales_order_id=1, amount=float(SUBCENT_MONEY))


def test_payment_schema_rejects_nonfinite_and_unbounded_amounts():
    for bad in ("Infinity", "NaN", "-Infinity"):
        with pytest.raises(ValidationError):
            PaymentIn(invoice_id=1, amount=bad)
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=1, amount=float(OVERFLOW_MONEY))
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=1, amount=float(SUBCENT_MONEY))


def test_money_bounds_match_the_storage_column():
    """The accepted maximum must equal what `Numeric(14, 2)` can actually hold."""
    assert InvoiceIn(sales_order_id=1, amount=float(MAX_STORED_MONEY)).amount == MAX_STORED_MONEY
    assert PaymentIn(invoice_id=1, amount=float(MAX_STORED_MONEY)).amount == MAX_STORED_MONEY
    for storage_type in (Invoice.__table__.c.amount.type, Payment.__table__.c.amount.type):
        assert (storage_type.precision, storage_type.scale) == (14, 2)


# --------------------------------------------------------------------------
# Behaviours this change must not disturb
# --------------------------------------------------------------------------

def test_invoice_still_404s_for_missing_order(client, auth_headers):
    r = client.post(
        "/api/finance/invoices",
        headers=auth_headers,
        json={"sales_order_id": 999_999_999, "amount": 10.0},
    )
    assert r.status_code == 404, r.text


def test_invoice_still_returns_the_existing_invoice(client, auth_headers):
    order_id = _make_order()
    first = _post_invoice(client, auth_headers, order_id, 250.0)
    assert first.status_code == 201, first.text
    second = _post_invoice(client, auth_headers, order_id, 999.0)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["invoice_no"] == first.json()["invoice_no"]


def test_create_invoice_keeps_the_fn04_sales_order_lock():
    """FN04 (8e42807e) made the existence check safe with NO KEY UPDATE.

    The amount bound is inserted *after* that locked read, so the lock must
    still be present, ordered first, and still `key_share=True`.
    """
    text = inspect.getsource(finance_routes.create_invoice)
    lock = "with_for_update(of=SalesOrder, key_share=True)"
    assert lock in text, "the FN04 NO KEY UPDATE lock was removed or weakened"
    assert "populate_existing()" in text, "the locked read must refetch the row"
    read = text.index(".with_for_update(")
    assert read < text.index("existing = db.query(Invoice)"), (
        "the locked sales-order read must happen before the invoice existence check"
    )


# --------------------------------------------------------------------------
# Real PostgreSQL: only here is `Numeric(14, 2)` actually enforced.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def money_bounds_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL NUMERIC(14,2) bounds")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Money-bound storage proof requires a loopback PostgreSQL URL without connection overrides")
    schema = f"fn07_money_bounds_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=2,
        max_overflow=0,
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _pg_actor(sessions) -> int:
    with sessions() as db:
        actor = User(
            name="FN07 money bounds actor",
            email=f"fn07-{uuid4().hex}@example.invalid",
            password_hash="test-only",
            factory_code="MIL",
            is_active=True,
        )
        db.add(actor)
        db.commit()
        return int(actor.id)


def _pg_order(sessions) -> int:
    with sessions() as db:
        so = SalesOrder(
            order_no=f"FN07-PG-{uuid4().hex[:10]}",
            status="confirmed",
            total_amount=500,
        )
        db.add(so)
        db.commit()
        return int(so.id)


def _pg_counts(sessions) -> tuple[int, int]:
    with sessions() as db:
        return db.query(Invoice).count(), db.query(AuditLog).filter(AuditLog.entity_type == "Invoice").count()


@pytest.mark.parametrize(
    "amount",
    [float(OVERFLOW_MONEY), float(SUBCENT_MONEY), float("inf"), float("nan")],
    ids=["column-overflow", "sub-cent", "infinite", "nan"],
)
def _create_invoice_through_endpoint(db, user, sales_order_id: int, amount):
    """Model the real request boundary: FastAPI validates the body before the route runs."""
    try:
        payload = InvoiceIn(sales_order_id=sales_order_id, amount=amount)
    except ValidationError as exc:
        raise HTTPException(422, "invalid body") from exc
    return finance_routes.create_invoice(payload, db, user)


@pytest.mark.parametrize(
    "amount",
    [float(OVERFLOW_MONEY), float(SUBCENT_MONEY), float("inf"), float("nan")],
    ids=["column-overflow", "sub-cent", "infinite", "nan"],
)
def test_postgres_rejects_bad_invoice_amount_before_any_write(money_bounds_postgres_sessions, amount):
    """Real `NUMERIC(14,2)` enforcement — the write must never be attempted."""
    sessions, _engine = money_bounds_postgres_sessions
    order_id = _pg_order(sessions)
    actor_id = _pg_actor(sessions)
    before = _pg_counts(sessions)
    with sessions() as db:
        user = db.get(User, actor_id)
        with pytest.raises(HTTPException) as excinfo:
            _create_invoice_through_endpoint(db, user, order_id, amount)
        assert excinfo.value.status_code == 422
        db.rollback()
    assert _pg_counts(sessions) == before, "a rejected amount wrote an invoice/audit row"


def test_postgres_stores_the_maximum_representable_amount(money_bounds_postgres_sessions):
    """The bound must not be tighter than the real column."""
    sessions, _engine = money_bounds_postgres_sessions
    order_id = _pg_order(sessions)
    actor_id = _pg_actor(sessions)
    with sessions() as db:
        user = db.get(User, actor_id)
        inv = finance_routes.create_invoice(
            InvoiceIn(sales_order_id=order_id, amount=float(MAX_STORED_MONEY)), db, user
        )
        # `create_invoice` commits, so read the stored value before the session closes.
        stored = Decimal(str(inv.amount))
        invoice_id = int(inv.id)
    with sessions() as db:
        assert Decimal(str(db.get(Invoice, invoice_id).amount)) == MAX_STORED_MONEY
    assert stored == MAX_STORED_MONEY


def test_postgres_column_would_reject_the_overflow_directly(money_bounds_postgres_sessions):
    """Sanity check that the enforced bound is the reason the route must reject."""
    sessions, engine = money_bounds_postgres_sessions
    order_id = _pg_order(sessions)
    with sessions() as db:
        db.add(Invoice(sales_order_id=order_id, invoice_no=f"FN07-RAW-{uuid4().hex[:10]}", amount=OVERFLOW_MONEY))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
