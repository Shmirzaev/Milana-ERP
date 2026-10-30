from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.libs.dto.fulfillment.package_workflows import PrintRunIn
from app.libs.enums.packaging import PackagingDepartment
from app.models import package_workflows_service
from app.schemas.packaging.manual_packages_persistence import (
    PackagePrintRunHeaderCommand,
    insert_package_print_run_header,
    insert_package_print_run_members,
)


class RecordingSession:
    def __init__(self):
        self.added = []
        self.batches = []
        self.flush_count = 0

    def add(self, row):
        self.added.append(row)

    def add_all(self, rows):
        self.batches.append(list(rows))

    def flush(self):
        self.flush_count += 1
        if self.flush_count == 1:
            self.added[0].id = 481


def test_print_run_persistence_keeps_header_and_manifest_flush_boundaries():
    db = RecordingSession()
    packages = [SimpleNamespace(id=31), SimpleNamespace(id=32)]
    received_at = datetime(2026, 10, 30, tzinfo=timezone.utc)

    run = insert_package_print_run_header(
        db,
        command=PackagePrintRunHeaderCommand(
            run_no="PRN-2026-000031",
            code="PACKRUN:test",
            actor_id=7,
            department=PackagingDepartment.MILANA,
            packages=tuple(packages),
            received_at=received_at,
        ),
    )
    snapshots = [{"package_no": "A"}, {"package_no": "B"}]
    insert_package_print_run_members(db, run=run, packages=packages, snapshots=snapshots)

    assert run.id == 481
    assert run.package_ids == [31, 32]
    assert run.created_by == 7
    assert run.packaging_department_code == "PKG"
    assert (run.received_by, run.received_at) == (7, received_at)
    assert [member.package_id for member in db.batches[0]] == [31, 32]
    assert [member.snapshot for member in db.batches[0]] == snapshots
    assert [member.run_id for member in db.batches[0]] == [481, 481]
    assert db.flush_count == 2


def test_print_run_replay_preserves_route_transaction_boundary(monkeypatch):
    commits = []
    db = SimpleNamespace(commit=lambda: commits.append("commit"))
    replay = {"id": 481, "run_no": "PRN-2026-000031"}
    monkeypatch.setattr(package_workflows_service, "lock_request", lambda *_args: None)
    monkeypatch.setattr(
        package_workflows_service,
        "replay_idempotent_response",
        lambda _db, **_kwargs: replay,
    )
    monkeypatch.setattr(
        package_workflows_service,
        "_validate_print_run_replay",
        lambda *_args: None,
    )
    authorization = package_workflows_service.PrintRunAuthorizationContext(
        actor=SimpleNamespace(id=7),
        can_access_all_print_runs=False,
    )
    payload = PrintRunIn(request_key=uuid4(), package_ids=[31])

    result = package_workflows_service.create_print_run(db, payload, authorization)

    assert result == replay
    assert commits == []
