from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.uploads import upload_session_factory


def failing_upload_session_factory(request_db: Session, message: str):
    base_factory = upload_session_factory(request_db)

    def create_session():
        worker_db = base_factory()

        def fail_commit() -> None:
            raise RuntimeError(message)

        worker_db.commit = fail_commit  # type: ignore[method-assign]
        return worker_db

    return create_session
