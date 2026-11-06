"""Challenge the approved public boundary, its real caller and write ownership."""
from dataclasses import replace
from typing import get_type_hints
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.db.session import SessionLocal
from app.libs.enums.fulfillment import FinishedGoodsStatus
from app.libs.enums.packaging import PackageStockKind
from app.libs.types.stock_reservation import PackDemand, PackReservationResult, PieceDemand, PieceReservationResult
from app.models.fulfillment import stock_service
from app.models import ready_stock_sales_service
from app.schemas import FinishedGoodsStock, Model, Package, PackageItem, ProductionOrder, SalesOrder, SalesOrderItem, StockReservation
from app.tests.test_sales_ready_packs import _packs


class NoDatabaseAccess:
    def __getattr__(self, name):
        raise AssertionError(f"Invalid command reached database attribute {name}")


PIECE = PieceDemand(1, None, "white", "M", 1)
PACK = PackDemand("line-a", 1, None, 1)


@pytest.mark.parametrize("demands", [
    (), [PIECE], (PACK,), (PIECE, PACK), (PIECE, PIECE),
    (replace(PIECE, color=" white "), PIECE),
    (replace(PIECE, quantity=-1),), (replace(PIECE, quantity=True),),
    (replace(PIECE, quantity=1.5),), (replace(PIECE, quantity="1"),),
    (replace(PIECE, model_id=0),), (replace(PIECE, brand_id=False),),
    (replace(PIECE, color=None),), (replace(PIECE, size=1),),
])
def test_piece_contract_rejects_malformed_inputs_before_queries_or_writes(demands):
    with pytest.raises(ValueError):
        stock_service.reserve_pieces(NoDatabaseAccess(), sales_order_id=1, reserved_by=None,
                                    stock_kind=PackageStockKind.STANDARD, demands=demands, fail_on_shortage=False)


@pytest.mark.parametrize("demands", [
    (), [PACK], (PIECE,), (PACK, PIECE), (PACK, PACK),
    (PACK, replace(PACK, demand_key="different-key")),
    (PACK, replace(PACK, model_id=2)),
    (replace(PACK, demand_key=""),), (replace(PACK, pack_count=0),),
    (replace(PACK, pack_count=-1),), (replace(PACK, pack_count=True),),
    (replace(PACK, pack_count=1.5),), (replace(PACK, pack_count="1"),),
    (replace(PACK, model_id=0),), (replace(PACK, brand_id=False),),
])
def test_pack_contract_rejects_malformed_inputs_before_queries_or_writes(demands):
    with pytest.raises(ValueError):
        stock_service.reserve_packs(NoDatabaseAccess(), sales_order_id=1, reserved_by=None, demands=demands)


@pytest.mark.parametrize("kind", ["standard", "first_grade", "second_grade", PackageStockKind.SECOND_GRADE, None])
def test_piece_contract_uses_real_enum_and_explicit_action_subset(kind):
    with pytest.raises(ValueError):
        stock_service.reserve_pieces(NoDatabaseAccess(), sales_order_id=1, reserved_by=None,
                                    stock_kind=kind, demands=(PIECE,), fail_on_shortage=False)


@pytest.mark.parametrize("operation", ["pieces", "packs"])
@pytest.mark.parametrize("order_id,actor", [(True, None), (0, None), (-1, None), ("1", None), (1, False), (1, -1)])
def test_invalid_actor_or_order_identity_is_refused_before_database_access(operation, order_id, actor):
    arguments = dict(sales_order_id=order_id, reserved_by=actor)
    if operation == "pieces":
        arguments.update(stock_kind=PackageStockKind.STANDARD, demands=(PIECE,), fail_on_shortage=False)
    else:
        arguments.update(demands=(PACK,))
    with pytest.raises(ValueError):
        getattr(stock_service, f"reserve_{operation}")(NoDatabaseAccess(), **arguments)


def test_real_public_annotations_and_canonical_complete_vocabularies():
    hints = get_type_hints(stock_service.reserve_pieces)
    assert hints["stock_kind"] is PackageStockKind
    assert hints["return"] is PieceReservationResult
    assert get_type_hints(stock_service.reserve_packs)["return"] is PackReservationResult
    assert "stock_kind" not in get_type_hints(stock_service.reserve_packs)
    assert [kind.value for kind in PackageStockKind] == ["standard", "first_grade", "second_grade"]
    assert [status.value for status in FinishedGoodsStatus] == ["available", "reserved", "sold", "damaged"]
    kind_constraint = next(c for c in Package.__table__.constraints if c.name == "ck_packages_stock_kind")
    status_constraint = next(c for c in FinishedGoodsStock.__table__.constraints if c.name == "ck_finished_goods_status")
    assert str(kind_constraint.sqltext) == "stock_kind IN ('standard', 'first_grade', 'second_grade')"
    assert str(status_constraint.sqltext) == "status IN ('available', 'reserved', 'sold', 'damaged')"


def test_pack_mapping_uses_real_unflushed_sales_lines_and_same_session_without_hidden_transaction(monkeypatch):
    first_model, first_packages = _packs((6,))
    second_model, second_packages = _packs((5,))
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"UNFLUSHED-{uuid4().hex[:10]}", order_type="branded_stock_sale", status="draft")
        db.add(order)
        db.flush()
        lines = [SalesOrderItem(sales_order_id=order.id, model_id=model_id, color="mixed", size="any",
                                quantity=0, requested_pack_count=1, unit_price=price, source_type="from_stock")
                 for model_id, price in [(second_model, 3), (first_model, 2)]]
        db.add_all(lines)
        assert [line.id for line in lines] == [None, None]
        original = ready_stock_sales_service.reserve_packs
        calls = []

        def reserve_same_session(session, **kwargs):
            assert session is db
            assert [line.id for line in lines] == [None, None]
            assert [d.demand_key for d in kwargs["demands"]] == ["0", "1"]
            assert all(type(d) is PackDemand for d in kwargs["demands"])
            result = original(session, **kwargs)
            assert result.piece_quantities_by_demand == {"0": 5, "1": 6}
            # Fulfillment has not mutated the caller's Sales rows.
            assert [line.quantity for line in lines] == [0, 0]
            assert order.status == "draft"
            calls.append(result)
            return result

        monkeypatch.setattr(ready_stock_sales_service, "reserve_packs", reserve_same_session)
        def forbid_commit(*args):
            raise AssertionError("Reservation helper must not commit")
        event.listen(db, "before_commit", forbid_commit)
        reservations = ready_stock_sales_service.reserve_ready_packs(db, so=order, lines=lines, user_id=1)
        assert len(calls) == 1
        assert [line.quantity for line in lines] == [5, 6]
        assert order.total_amount == 27
        assert order.status == "ready"
        assert [line.id for line in lines] == [None, None], "No new flush introduced by line correlation"
        assert sum(row["qty"] for row in reservations) == 11
        db.flush()
        assert db.query(StockReservation).filter(StockReservation.sales_order_id == order.id).count() == 4
        event.remove(db, "before_commit", forbid_commit)
        db.rollback()
    with SessionLocal() as db:
        rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(first_packages + second_packages)).all()
        assert sum(row.available_qty for row in rows) == 11
        assert sum(row.reserved_qty for row in rows) == 0


def test_piece_first_grade_and_zero_contract_preserve_current_behavior():
    with SessionLocal() as db:
        suffix = uuid4().hex[:10]
        model = Model(code=f"GRADE-M-{suffix}", name="First grade contract", status="approved")
        db.add(model)
        db.flush()
        model_id = model.id
        production = ProductionOrder(production_no=f"GRADE-PO-{suffix}", model_id=model_id,
                                     production_type="branded_stock", planned_quantity=1, status="completed")
        order = SalesOrder(order_no=f"GRADE-{suffix}", order_type="branded_stock_sale", status="draft")
        db.add_all([production, order])
        db.flush()
        package = Package(package_no=f"GRADE-P-{suffix}", barcode=f"GRADE-P-{suffix}",
                          production_order_id=production.id, model_id=model_id, color="white",
                          stock_kind="first_grade", total_quantity=1, capacity=1, status="received_in_storage")
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(package_id=package.id, model_id=model_id, color="white", size="M",
                                   quantity=1, available_qty=1, reserved_qty=0, sold_qty=0, status="available")
        db.add_all([stock, PackageItem(package_id=package.id, model_id=model_id, color="white", size="M", quantity=1)])
        db.flush()
        zero_demand = PieceDemand(model_id, None, stock.color, stock.size, 0)
        with pytest.raises(HTTPException) as refusal:
            stock_service.reserve_pieces(db, sales_order_id=order.id, reserved_by=None,
                                         stock_kind=PackageStockKind.FIRST_GRADE, demands=(zero_demand,), fail_on_shortage=False)
        assert refusal.value.status_code == 409
        result = stock_service.reserve_pieces(db, sales_order_id=order.id, reserved_by=None,
                                             stock_kind=PackageStockKind.FIRST_GRADE,
                                             demands=(replace(zero_demand, quantity=1),), fail_on_shortage=True)
        assert result.reservations == ({"stock_id": stock.id, "package_id": package.id, "qty": 1},)
        assert result.shortages == ()
        assert (stock.available_qty, stock.reserved_qty, stock.status) == (0, 1, "reserved")
        assert order.status == "draft", "Fulfillment must not write Sales status"
        db.rollback()
