"""Explicit, atomic application of a reviewed inventory plan via ERP handlers.

Loaded inside the verified live container by run_fabric_reconciliation.py.
No standalone default execution and no direct SQL business-data mutation.
"""
import base64
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.routes.inventory import receive_stock, update_batch
from app.core.config import settings
from app.core.deps import user_permissions
from app.models import AuditLog, StockBatch, User
from app.schemas.inventory import StockBatchIn, StockBatchUpdate
from app.services.audit import log_action
from app.services.image_storage import convert_image_to_webp, prebuild_webp_thumbnails


class AtomicSession(Session):
    def commit(self):
        self.flush()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def assert_unchanged(expected, actual):
    for key in expected:
        if key != 'snapshot_time' and expected[key] != actual[key]:
            raise ValueError('Live evidence changed: ' + key)


