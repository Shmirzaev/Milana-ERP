"""Reviewed XJ3062 family merge and Besttex line renaming; default is read-only."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.api.routes.catalog import _model_code_parts, _model_group_payload
from app.db.session import SessionLocal
from app.models import Model, SewingAssignment, SewingFlow, WorkOrder
from app.services.audit import log_action

SOURCE_IDS = {7385, 7386, 7387, 7388, 7418, 7644, 7645, 7646, 7647, 7648,
              7649, 7650, 7651, 7652, 7653, 8054, 8110}
NAMES = ["Oydinoy Mamadaliyeva", "Miyassar Yunusova", "Teshaboyeva Nargiza",
         "Shaxnoza Maxsimova", "Minura Toshboyeva", "Muqadamxon Muhammadjon qizi",
         "Kamola Xoliqova", "Nargiza Xoliqova"]
CANONICAL = "ХJ3062"  # Existing 138-variant family uses Cyrillic Х.
ACTIVE = ("waiting", "pending", "collected", "ready", "in_progress", "paused", "new", "planning")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '10s'"))
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        query = db.query(Model).filter(Model.catalog_scope == "standard").filter(
            text("NOT is_legacy_import AND model_group_key IN ('model:xj3062', 'model:хj3062')")
        ).order_by(Model.id)
        models = (query.with_for_update() if args.apply else query).all()
        source = [m for m in models if _model_code_parts(m)[0] == "XJ3062"]
        target = [m for m in models if _model_code_parts(m)[0] == CANONICAL]
        assert len(target) in (139, 156), "Unexpected canonical family membership"
        assert {m.id for m in source} in (SOURCE_IDS, set()), "Unreviewed source family membership"
        assert len(models) == 156, "Family membership changed; review before merging"
        variants = [_model_code_parts(m)[1].upper().removeprefix("V-") for m in models if _model_code_parts(m)[1]]
        assert len(variants) == len(set(variants)) == 155, "Conflicting duplicate variant numbers"
        line_query = db.query(SewingFlow).filter(SewingFlow.factory_code == "BST").order_by(SewingFlow.code)
        lines = (line_query.with_for_update() if args.apply else line_query).all()
        assert [f.id for f in lines] == list(range(96, 112))
        assert [f.code for f in lines] == [f"BST-BAND-{i:02d}" for i in range(1, 17)]
        retiring = [f.id for f in lines[8:]]
        assert not db.query(SewingAssignment.id).filter(
            SewingAssignment.sewing_flow_id.in_(retiring),
            SewingAssignment.status.in_(("planned", "in_progress")),
        ).first(), "A retiring line has active assignments"
        assert not db.query(WorkOrder.id).filter(
            WorkOrder.sewing_flow_id.in_(retiring), WorkOrder.status.in_(ACTIVE),
        ).first(), "A retiring line has an active direct work order"
        for i, flow in enumerate(lines):
            assert flow.name in (f"{i+1}-Band", NAMES[i] if i < 8 else f"{i+1}-Band")
        old = {"models": [{"id": m.id, "general": deepcopy((m.details_json or {}).get("general", {}))} for m in source],
               "lines": [{"id": f.id, "name": f.name, "is_active": f.is_active} for f in lines]}
        result = {"source_model_rows": len(source), "family_variants": len(variants),
                  "line_names": NAMES, "retired_line_ids": retiring, "applied": args.apply}
        if not source and all(f.name == NAMES[i] and f.is_active for i, f in enumerate(lines[:8])) and all(not f.is_active for f in lines[8:]):
            result["already_applied"] = True
            print(json.dumps(result)); return
        if args.apply:
            for model in source:
                details = deepcopy(model.details_json or {})
                general = dict(details.get("general") or {})
                general["model_no"] = CANONICAL
                if "modelNo" in general:
                    general["modelNo"] = CANONICAL
                details["general"] = general
                model.details_json = details
            for i, flow in enumerate(lines):
                flow.is_active = i < 8
                if i < 8:
                    flow.name = NAMES[i]
            db.flush()
            keys = db.execute(text("SELECT DISTINCT model_group_key FROM models WHERE id = ANY(:ids)"), {"ids": [m.id for m in models]}).scalars().all()
            assert keys == ["model:хj3062"]
            assert _model_group_payload(models, compact=True)["variant_count"] == 155
            audit = log_action(db, None, "reconcile", "ModelFamilyAndSewingFlows", None,
                               old_value=old, new_value={**result, "canonical_model_no": CANONICAL,
                                                        "original_codes_and_references_preserved": True})
            db.flush(); result["audit_id"] = audit.id
            db.commit()
        print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
