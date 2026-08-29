from __future__ import annotations

import argparse

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models import SewingFlow
from app.services.audit import log_action


EXPECTED_CURRENT_NAMES = {
    "SEW-01": "Bozorova",
    "SEW-06": "Shaxnoza opa",
    "SEW-07": "Jalilova",
    "SEW-09": "Dilafruz opa",
    "SEW-10": "Nargiza opa",
    "SEW-12": "Muxlisa",
    "SEW-13": "Sevara",
}

TARGET_NAMES = {
    "SEW-01": "Bozorova Nargiza",
    "SEW-06": "Botirova Shaxnoza",
    "SEW-07": "Jalolova Nargiza",
    "SEW-09": "Akbarova Dilafruz",
    "SEW-10": "Maxmudova Nargiza - 1",
    "SEW-12": "Botirova Muxlisa",
    "SEW-13": "Maxmudova Nargiza - 2",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded rename of the seven active production sewing lines")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the guarded update. Without this flag the script performs a dry run.",
    )
    args = parser.parse_args()

    codes = tuple(TARGET_NAMES)
    with SessionLocal() as db:
        if args.apply:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

        statement = select(SewingFlow).where(SewingFlow.code.in_(codes)).order_by(SewingFlow.code)
        if args.apply:
            statement = statement.with_for_update()
        rows = list(db.scalars(statement))
        by_code = {row.code: row for row in rows}

        missing = sorted(set(codes) - set(by_code))
        unexpected = {
            code: row.name
            for code, row in by_code.items()
            if row.name not in {EXPECTED_CURRENT_NAMES[code], TARGET_NAMES[code]}
        }
        inactive = sorted(code for code, row in by_code.items() if not row.is_active)
        if missing or unexpected or inactive:
            raise RuntimeError(
                f"guard failed: missing={missing}, unexpected_names={unexpected}, inactive={inactive}"
            )

        conflicts = list(
            db.scalars(
                select(SewingFlow).where(
                    SewingFlow.name.in_(tuple(TARGET_NAMES.values())),
                    SewingFlow.code.not_in(codes),
                )
            )
        )
        if conflicts:
            raise RuntimeError(
                "target name conflict: "
                + ", ".join(f"{row.code}={row.name}" for row in conflicts)
            )

        for code in codes:
            row = by_code[code]
            print(f"{code}: {row.name} -> {TARGET_NAMES[code]}")

        if not args.apply:
            db.rollback()
            print("dry_run=ok")
            return 0

        audit_rows = []
        for code in codes:
            row = by_code[code]
            old_name = row.name
            new_name = TARGET_NAMES[code]
            if old_name == new_name:
                continue
            row.name = new_name
            audit_rows.append(
                log_action(
                    db,
                    None,
                    "update",
                    "SewingFlow",
                    row.id,
                    old_value={"code": code, "name": old_name},
                    new_value={"code": code, "name": new_name},
                )
            )

        db.commit()
        print("audit_ids=" + ",".join(str(row.id) for row in audit_rows))

    with SessionLocal() as db:
        actual = {
            row.code: row.name
            for row in db.scalars(
                select(SewingFlow).where(SewingFlow.code.in_(codes)).order_by(SewingFlow.code)
            )
        }
        if actual != TARGET_NAMES:
            raise RuntimeError(f"post-commit verification failed: {actual}")
        print("applied=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
