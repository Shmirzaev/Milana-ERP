import asyncio
from threading import get_ident

import pytest

from app.core.uploads import run_upload_db_work, upload_session_factory
from app.models import SystemSetting
from app.tests.conftest import TestSessionLocal


def test_upload_db_work_uses_fresh_worker_session_off_event_loop_and_rolls_back():
    loop_thread = get_ident()
    setting_key = "perf40-upload-worker-rollback"

    with TestSessionLocal() as request_db:
        sessions = upload_session_factory(request_db)

        def failing_work(worker_db):
            assert worker_db is not request_db
            assert get_ident() != loop_thread
            worker_db.add(SystemSetting(key=setting_key, value_json={"created": True}))
            worker_db.flush()
            raise RuntimeError("synthetic upload transaction failure")

        with pytest.raises(RuntimeError, match="synthetic upload transaction failure"):
            asyncio.run(run_upload_db_work(sessions, failing_work, commit=True))

    with TestSessionLocal() as db:
        assert db.query(SystemSetting).filter(SystemSetting.key == setting_key).first() is None
