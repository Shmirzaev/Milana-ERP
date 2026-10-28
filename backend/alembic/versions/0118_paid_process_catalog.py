"""Deduplicated paid-process catalogue, preserving every model rate and issued QR."""
from alembic import op
import sqlalchemy as sa
import unicodedata
import hashlib

revision = "0118_paid_process_catalog"
down_revision = "0117_package_quantity_evidence"
branch_labels = None
depends_on = None

# Freeze seed interpretation with this migration so future application changes
# cannot reinterpret historical sections or factory ownership on fresh installs.
SECTIONS = {"sewing", "cutting", "packaging", "cleaning", "pressing", "control", "storage", "tikuv", "transfer", "snaps", "buttons", "cord", "sorting"}
ALIASES = {"пошив": "sewing", "tikuv": "tikuv", "крой": "cutting", "kroy": "cutting",
           "упаковка": "packaging", "upakovka": "packaging", "чистка": "cleaning",
           "chistka": "cleaning", "глажка": "pressing", "dazmol": "pressing",
           "контроль": "control", "kontrol": "control", "nazorat": "control", "склад": "storage",
           "трансфер": "transfer", "кнопки": "snaps", "пуговицы": "buttons", "шнур": "cord", "тасниф": "sorting"}
FACTORIES = {"MIL": "MIL", "MILANA": "MIL", "SML": "MIL", "BST": "BST", "BESTTEX": "BST", "BTX": "BST", "ECO": "ECO", "ECO_COTTON": "ECO", "ECOCOTTON": "ECO"}


def normalized_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def process_section(row):
    source = normalized_name(str(row.get("sourceStage") or row.get("source_stage") or ""))
    section = normalized_name(str(row.get("section") or "sewing"))
    return source if source in SECTIONS else ALIASES.get(source, section if section in SECTIONS else ALIASES.get(section, "sewing"))


def seed_factories(row):
    value = row.get("sewingFactory", row.get("sewing_factory", row.get("factory", row.get("company"))))
    if value in (None, ""):
        return ["MIL", "BST", "ECO"]
    normalized = "_".join(str(value).strip().upper().replace("-", " ").replace("_", " ").split())
    factory = FACTORIES.get(normalized)
    # Invalid explicit ownership must never become shared across factories.
    return [factory] if factory else []


def upgrade():
    table = op.create_table(
        "paid_processes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.String(64), nullable=False),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("factory_code", "normalized_key", "section", name="uq_paid_process_identity"),
    )
    op.create_index("ix_paid_processes_factory_code", "paid_processes", ["factory_code"])
    models = sa.table("models", sa.column("id", sa.Integer), sa.column("catalog_scope", sa.String), sa.column("details_json", sa.JSON))
    identities = set()
    inserts = []
    for (details,) in op.get_bind().execute(sa.select(models.c.details_json).where(models.c.catalog_scope == "standard").order_by(models.c.id)):
        operations = details.get("paid_operations", details.get("paidOperations", [])) if isinstance(details, dict) else []
        for row in operations if isinstance(operations, list) else []:
            if not isinstance(row, dict):
                continue
            name = " ".join(str(row.get("name") or "").split())[:255]
            if not name:
                continue
            identity_name = normalized_name(name)
            identity_key = hashlib.sha256(identity_name.encode("utf-8")).hexdigest()
            for code in seed_factories(row):
                key = (code, identity_name, process_section(row))
                if key in identities:
                    continue
                identities.add(key)
                inserts.append(dict(factory_code=code, normalized_name=key[1], normalized_key=identity_key, section=key[2], name=name,
                                    code=f"OP-{len(inserts) + 1:04d}"))
    if inserts:
        op.bulk_insert(table, inserts)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM paid_processes")).scalar():
        raise RuntimeError("Preserve the paid-process catalogue; downgrade requires a reviewed backup")
    op.drop_table("paid_processes")
