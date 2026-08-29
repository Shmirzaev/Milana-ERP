from uuid import uuid4

import pytest

from app.api.routes.packages import storage_map
from app.api.routes.shipments import _find_package_for_scan
from app.db.session import SessionLocal
from app.models import (
    Brand,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageBarcodeAlias,
    PackageItem,
    Shipment,
    ShipmentPackage,
    ShipmentScanLog,
)
from scripts.import_legacy_ready_stock import (
    current_piece_quantity,
    display_color,
    payload_checksum,
    profile_rows,
)
from scripts.prepare_legacy_ready_stock import COL, EXPECTED_COLUMNS, prepare
from scripts.canonicalize_legacy_stock_models import reconcile as canonicalize
from scripts.reconcile_legacy_stock_models import reconcile


def _legacy_package(db, *, suffix: str, model_id: int, receipt_id: int) -> Package:
    package = Package(
        package_no=f"LEG-TEST-{suffix}",
        barcode=f"LEGACY:TEST-{suffix}",
        production_order_id=None,
        legacy_receipt_id=receipt_id,
        model_id=model_id,
        color="BLUE",
        package_type="legacy_stock",
        total_quantity=5,
        capacity=60,
        status="received_in_storage",
    )
    db.add(package)
    db.flush()
    return package


def test_legacy_profile_requires_unique_whole_piece_rows():
    rows = [
        {
            "source_record_id": "1001",
            "quantity": "6",
            "available": "6.00",
            "unit": "шт.",
            "model_code": "XJ100",
        },
        {
            "source_record_id": "1002",
            "quantity": "3.00",
            "available": "2.00",
            "unit": "кг",
            "finished_name": "Legacy gown",
        },
    ]

    profile = profile_rows(rows)

    assert profile["row_count"] == 2
    assert profile["piece_quantity"] == 9
    assert profile["available_piece_quantity"] == 8
    assert profile["depleted_piece_quantity"] == 1
    assert profile["unmapped_model_rows"] == 1
    assert profile["available_quantity_mismatch_rows"] == 1
    assert current_piece_quantity(rows[1], "1002") == 2
    assert profile["units"] == {"шт.": 1, "кг": 1}
    assert payload_checksum(rows[0]) == payload_checksum(dict(reversed(list(rows[0].items()))))
    assert display_color({"color": "RED", "variant": "V-22"}) == "RED · V-22"


def test_reused_legacy_alias_selects_next_unscanned_attached_package():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        brand = Brand(name=f"Legacy Test {token}", is_active=True)
        db.add(brand)
        db.flush()
        model = Model(
            code=f"LEGACY-TEST-{token}",
            name="Legacy test model",
            brand_id=brand.id,
            status="approved",
        )
        db.add(model)
        db.flush()

        receipts = []
        for index in (1, 2):
            receipt = LegacyStockReceipt(
                source_system="UZERP",
                source_warehouse_id="18",
                source_record_id=f"{token}-{index}",
                source_checksum=f"{index:064d}",
                source_payload={"row": index},
            )
            db.add(receipt)
            db.flush()
            receipts.append(receipt)

        first = _legacy_package(db, suffix=f"{token}-1", model_id=model.id, receipt_id=receipts[0].id)
        second = _legacy_package(db, suffix=f"{token}-2", model_id=model.id, receipt_id=receipts[1].id)
        shared_code = f"OLD-QR-{token}"
        db.add_all(
            [
                PackageBarcodeAlias(package_id=first.id, code=shared_code, code_type="external_barcode"),
                PackageBarcodeAlias(package_id=second.id, code=shared_code, code_type="external_barcode"),
            ]
        )
        shipment = Shipment(shipment_no=f"SHIP-LEG-{token}", status="draft")
        db.add(shipment)
        db.flush()
        db.add_all(
            [
                ShipmentPackage(shipment_id=shipment.id, package_id=first.id, quantity=5),
                ShipmentPackage(shipment_id=shipment.id, package_id=second.id, quantity=5),
            ]
        )
        db.commit()

        found, matched = _find_package_for_scan(db, shared_code, shipment_id=shipment.id)
        assert found.id == first.id
        assert matched == shared_code

        db.add(
            ShipmentScanLog(
                shipment_id=shipment.id,
                package_id=first.id,
                scanned_code=shared_code,
                scan_result="matched",
            )
        )
        db.commit()

        found_next, matched_next = _find_package_for_scan(db, shared_code, shipment_id=shipment.id)
        assert found_next.id == second.id
        assert matched_next == shared_code
    finally:
        db.close()


def test_package_scanner_resolves_sticker_qr_and_returns_source_evidence(client, auth_headers):
    token = uuid4().hex[:10]
    qr_code = f"uzerp_ii_{int(token[:6], 16)}_2"
    db = SessionLocal()
    try:
        model = Model(code=f"STICKER-{token}", name="Sticker evidence model", status="approved")
        db.add(model)
        db.flush()
        receipt = LegacyStockReceipt(
            source_system="UZERP_STICKER_PHOTO",
            source_warehouse_id="18",
            source_warehouse_name="TAYYOR MAHSULOT OMBORI",
            source_record_id=qr_code,
            source_checksum="a" * 64,
            source_payload={
                "client": "0001",
                "model_number": "TJ2049",
                "article": "V-4326",
                "color": "Rotatsion Baski",
                "product": "1201 Туника",
                "fabric": "30/1 CMP PENYE",
                "sizes": ["XL-50", "2XL-52"],
                "weight_kg": 20.7,
                "quantity": 60,
                "qr_code": qr_code,
                "inventory_no": "3769",
                "location": "Paxtaobod",
                "source_photo": "photo_1.jpg",
                "source_photo_sha256": "b" * 64,
            },
        )
        db.add(receipt)
        db.flush()
        package = _legacy_package(db, suffix=token, model_id=model.id, receipt_id=receipt.id)
        package.weight_kg = 20.7
        package.total_quantity = 60
        db.add(PackageBarcodeAlias(package_id=package.id, code=qr_code, code_type="legacy_sticker_qr"))
        db.commit()
        package_id = package.id
    finally:
        db.close()

    response = client.get(f"/api/packages/barcode/{qr_code}", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == package_id
    assert body["legacy_source"] == {
        "source_system": "UZERP_STICKER_PHOTO",
        "source_record_id": qr_code,
        "source_warehouse_name": "TAYYOR MAHSULOT OMBORI",
        "imported_at": body["legacy_source"]["imported_at"],
        "client": "0001",
        "model_number": "TJ2049",
        "article": "V-4326",
        "color": "Rotatsion Baski",
        "product": "1201 Туника",
        "fabric": "30/1 CMP PENYE",
        "sizes": ["XL-50", "2XL-52"],
        "weight_kg": 20.7,
        "quantity": 60,
        "qr_code": qr_code,
        "inventory_no": "3769",
        "location": "Paxtaobod",
        "source_photo": "photo_1.jpg",
        "source_photo_sha256": "b" * 64,
    }


def test_warehouse_stock_can_include_unplaced_legacy_packages():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        model = Model(code=f"LEGACY-MAP-{token}", name="Legacy map test", status="approved")
        db.add(model)
        db.flush()
        receipt = LegacyStockReceipt(
            source_system="UZERP",
            source_warehouse_id="18",
            source_record_id=f"map-{token}",
            source_checksum=f"{token:0<64}",
            source_payload={"row": token},
        )
        db.add(receipt)
        db.flush()
        package = _legacy_package(db, suffix=token, model_id=model.id, receipt_id=receipt.id)
        db.commit()

        placed_only = storage_map(db, None, model_query=token)
        with_unplaced = storage_map(db, None, model_query=token, include_unplaced=True)

        assert all(row["id"] != package.id for row in placed_only["placements"])
        assert any(row["id"] == package.id for row in with_unplaced["placements"])
        assert with_unplaced["summary"]["packages_on_map"] == 0
        assert with_unplaced["summary"]["packages_in_storage"] >= 1
    finally:
        db.close()


def test_legacy_model_reconciliation_updates_identity_without_changing_quantity():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        legacy_model = Model(
            code=f"LEGACY-RECON-{token}",
            name="Unresolved legacy",
            status="approved",
        )
        target_model = Model(
            code=f"PJ-RECON-{token}",
            name="Resolved pajama",
            status="approved",
        )
        db.add_all([legacy_model, target_model])
        db.flush()
        receipt = LegacyStockReceipt(
            source_system="UZERP",
            source_warehouse_id="18",
            source_record_id=f"recon-{token}",
            source_checksum=f"{token:0<64}",
            source_payload={"color": "BURGUNDY", "model_code": "", "variant": ""},
        )
        db.add(receipt)
        db.flush()
        package = _legacy_package(
            db,
            suffix=f"recon-{token}",
            model_id=legacy_model.id,
            receipt_id=receipt.id,
        )
        item = PackageItem(
            package_id=package.id,
            model_id=legacy_model.id,
            color="BURGUNDY",
            size="M-46",
            quantity=5,
        )
        stock = FinishedGoodsStock(
            package_id=package.id,
            model_id=legacy_model.id,
            color="BURGUNDY",
            size="M-46",
            quantity=5,
            available_qty=5,
            reserved_qty=0,
            sold_qty=0,
            status="available",
        )
        db.add_all([item, stock])
        db.commit()
        source_payload_before = dict(receipt.source_payload)
        mapping = {
            "auto_matches": [
                {
                    "source_record_id": receipt.source_record_id,
                    "target_model_code": target_model.code,
                    "target_variant": "V-77",
                    "evidence_methods": ["exact_item_barcode", "exact_sewing_barcode"],
                }
            ]
        }

        applied = reconcile(
            db,
            mapping,
            mapping_sha256="a" * 64,
            apply=True,
            mapping_reference="test-mapping.json",
        )

        db.refresh(package)
        db.refresh(item)
        db.refresh(stock)
        db.refresh(receipt)
        assert applied["changed_rows"] == 1
        assert applied["before_totals"] == applied["after_totals"]
        assert package.model_id == target_model.id
        assert item.model_id == target_model.id
        assert stock.model_id == target_model.id
        assert package.color == "BURGUNDY · V-77"
        assert item.color == package.color
        assert stock.color == package.color
        assert stock.quantity == 5
        assert stock.available_qty == 5
        assert receipt.source_payload == source_payload_before

        repeated = reconcile(
            db,
            mapping,
            mapping_sha256="a" * 64,
            apply=True,
            mapping_reference="test-mapping.json",
        )
        assert repeated["changed_rows"] == 0
        assert repeated["skipped_existing"] == 1
    finally:
        db.close()


def test_legacy_model_reconciliation_blocks_package_that_is_no_longer_untouched():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        legacy_model = Model(code=f"LEGACY-BLOCK-{token}", name="Legacy", status="approved")
        target_model = Model(code=f"PJ-BLOCK-{token}", name="Target", status="approved")
        db.add_all([legacy_model, target_model])
        db.flush()
        receipt = LegacyStockReceipt(
            source_system="UZERP",
            source_warehouse_id="18",
            source_record_id=f"blocked-{token}",
            source_checksum=f"{token:0<64}",
            source_payload={"color": "BLUE"},
        )
        db.add(receipt)
        db.flush()
        package = _legacy_package(
            db,
            suffix=f"blocked-{token}",
            model_id=legacy_model.id,
            receipt_id=receipt.id,
        )
        package.status = "reserved"
        db.add_all(
            [
                PackageItem(
                    package_id=package.id,
                    model_id=legacy_model.id,
                    color="BLUE",
                    size="L-48",
                    quantity=5,
                ),
                FinishedGoodsStock(
                    package_id=package.id,
                    model_id=legacy_model.id,
                    color="BLUE",
                    size="L-48",
                    quantity=5,
                    available_qty=5,
                    reserved_qty=0,
                    sold_qty=0,
                    status="available",
                ),
            ]
        )
        db.commit()

        with pytest.raises(ValueError, match="no longer untouched storage stock"):
            reconcile(
                db,
                {
                    "auto_matches": [
                        {
                            "source_record_id": receipt.source_record_id,
                            "target_model_code": target_model.code,
                            "target_variant": "V-88",
                            "evidence_methods": ["unique_order_product"],
                        }
                    ]
                },
                mapping_sha256="b" * 64,
                apply=False,
                mapping_reference="test-mapping.json",
            )
    finally:
        db.rollback()
        db.close()


def test_legacy_canonicalization_links_exact_variant_and_restores_prior_noncanonical_match():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        legacy_brand = Brand(name=f"Legacy Canon {token}", is_active=True)
        real_brand = Brand(name=f"Real Canon {token}", is_active=True)
        db.add_all([legacy_brand, real_brand])
        db.flush()
        duplicate_model = Model(
            code=f"TJ{token}",
            name="Imported duplicate",
            brand_id=legacy_brand.id,
            details_json={"legacy_import": True},
            status="approved",
        )
        fallback_model = Model(
            code=f"LEGACY-{token}",
            name="Internal fallback",
            brand_id=legacy_brand.id,
            details_json={"legacy_import": True},
            status="approved",
        )
        canonical_model = Model(
            code=f"ТJ-{token}-4681",
            name="Canonical variant",
            brand_id=real_brand.id,
            details_json={
                "general": {
                    "model_no": f"ТJ-{token}",
                    "variant_no": "4681",
                }
            },
            status="approved",
        )
        prior_wrong_model = Model(
            code=f"WRONG-{token}",
            name="Prior noncanonical match",
            brand_id=legacy_brand.id,
            details_json={"legacy_import": True},
            status="approved",
        )
        db.add_all(
            [duplicate_model, fallback_model, canonical_model, prior_wrong_model]
        )
        db.flush()

        def add_stock(source_id: str, model: Model, quantity: int):
            receipt = LegacyStockReceipt(
                source_system="UZERP",
                source_warehouse_id="18",
                source_record_id=source_id,
                source_checksum=f"{token:0<64}",
                source_payload={"model_code": model.code, "variant": "V-4681"},
            )
            db.add(receipt)
            db.flush()
            package = _legacy_package(
                db,
                suffix=source_id,
                model_id=model.id,
                receipt_id=receipt.id,
            )
            package.brand_id = model.brand_id
            item = PackageItem(
                package_id=package.id,
                model_id=model.id,
                color="BLUE · V-4681",
                size="M-46",
                quantity=quantity,
            )
            stock = FinishedGoodsStock(
                package_id=package.id,
                model_id=model.id,
                brand_id=model.brand_id,
                color="BLUE · V-4681",
                size="M-46",
                quantity=quantity,
                available_qty=quantity,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            )
            db.add_all([item, stock])
            db.flush()
            return receipt, package, item, stock

        exact = add_stock(f"canonical-{token}", duplicate_model, 7)
        restored = add_stock(f"restore-{token}", prior_wrong_model, 5)
        db.commit()
        payload = {
            "canonical_rows": [
                {
                    "source_record_id": exact[0].source_record_id,
                    "package_id": exact[1].id,
                    "available_quantity": 7,
                    "expected_current_model_id": duplicate_model.id,
                    "expected_current_model_code": duplicate_model.code,
                    "target_model_id": canonical_model.id,
                    "target_model_code": canonical_model.code,
                }
            ],
            "restore_rows": [
                {
                    "source_record_id": restored[0].source_record_id,
                    "package_id": restored[1].id,
                    "available_quantity": None,
                    "expected_current_model_id": prior_wrong_model.id,
                    "expected_current_model_code": prior_wrong_model.code,
                    "target_model_id": fallback_model.id,
                    "target_model_code": fallback_model.code,
                }
            ],
        }

        result = canonicalize(
            db,
            payload,
            mapping_sha256="c" * 64,
            apply=True,
            mapping_reference="test-canonical.json",
        )
        assert result["changed_rows"] == 2
        assert result["before_totals"] == result["after_totals"]
        for row in exact[1:]:
            db.refresh(row)
        for row in restored[1:]:
            db.refresh(row)
        assert exact[1].model_id == canonical_model.id
        assert exact[2].model_id == canonical_model.id
        assert exact[3].model_id == canonical_model.id
        assert exact[1].brand_id == real_brand.id
        assert exact[3].brand_id == real_brand.id
        assert exact[3].available_qty == 7
        assert restored[1].model_id == fallback_model.id
        assert restored[2].model_id == fallback_model.id
        assert restored[3].model_id == fallback_model.id

        repeated = canonicalize(
            db,
            payload,
            mapping_sha256="c" * 64,
            apply=True,
            mapping_reference="test-canonical.json",
        )
        assert repeated["changed_rows"] == 0
        assert repeated["skipped_existing"] == 2
    finally:
        db.close()


def _report_row(
    row_number: int,
    source_record_id: str,
    *,
    external_barcode: str = "",
    model_code: str = "",
    model_name: str = "",
    variant: str = "",
) -> list[str]:
    row = [""] * EXPECTED_COLUMNS
    row[COL["row_number"]] = str(row_number)
    row[COL["source_record_id"]] = source_record_id
    row[COL["warehouse"]] = "TAYYOR MAHSULOT OMBORI"
    row[COL["unit"]] = "шт."
    row[COL["quantity"]] = "6"
    row[COL["available"]] = "6.00"
    row[COL["external_barcode"]] = external_barcode
    row[COL["model_code"]] = model_code
    row[COL["model_name"]] = model_name
    row[COL["variant"]] = variant
    return row


def test_prepare_legacy_stock_joins_model_mapping_and_profiles_quantity():
    primary = [
        _report_row(1, "1001", external_barcode="EXT-1"),
        _report_row(2, "1002", model_code="PJ-2", model_name="Pajama", variant="V-2"),
    ]
    secondary = [
        _report_row(
            1,
            "map-1",
            external_barcode="EXT-1",
            model_code="XJ-1",
            model_name="Gown",
            variant="V-1",
        )
    ]

    payload, profile = prepare(primary, secondary, expected_rows=2)

    assert profile["row_count"] == 2
    assert profile["piece_quantity"] == 12
    assert profile["available_piece_quantity"] == 12
    assert profile["model_mapping"] == {
        "direct": 1,
        "external_barcode": 1,
        "sewing_barcode": 0,
        "customer_order_product": 0,
        "order_product": 0,
        "customer_order": 0,
        "order": 0,
        "unresolved": 0,
        "ambiguous_secondary_codes": 0,
    }
    assert payload["rows"][0]["model_code"] == "XJ-1"
    assert payload["rows"][0]["variant"] == "V-1"
    assert payload["source"]["expected_quantity"] == 12
    assert payload["source"]["expected_available_quantity"] == 12


def test_prepare_legacy_stock_rejects_mixed_or_gapped_snapshot():
    primary = [
        _report_row(1, "1001"),
        _report_row(3, "1002"),
    ]

    with pytest.raises(ValueError, match="sequence is not contiguous"):
        prepare(primary, [], expected_rows=2)
