from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes.production import _gate_record_submission


def test_record_submission_is_allowed_after_deadline() -> None:
    work_order = SimpleNamespace(
        is_blocked=False,
        block_reason=None,
        deadline=datetime.now(timezone.utc) - timedelta(days=1),
        status="in_progress",
    )

    _gate_record_submission(work_order)


def test_explicitly_blocked_work_order_still_rejects_submission() -> None:
    work_order = SimpleNamespace(
        is_blocked=True,
        block_reason="Quality hold",
        deadline=datetime.now(timezone.utc) - timedelta(days=1),
        status="in_progress",
    )

    with pytest.raises(HTTPException, match="Quality hold") as exc_info:
        _gate_record_submission(work_order)

    assert exc_info.value.status_code == 409
