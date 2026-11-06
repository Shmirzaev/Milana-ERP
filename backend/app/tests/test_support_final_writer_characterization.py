"""Shared rows keep their values and the caller's transaction boundary."""

from types import SimpleNamespace

from sqlalchemy import event

from app.models import bundles_service, packages_service
from app.models.employee_reconciliation_service import reconcile_employees
from app.schemas import BusinessOrderAlias, Employee, Notification, SystemSetting, User
from app.tests.test_support_variant_reference import reference_db  # noqa: F401 - pytest fixture, used by name


def test_bundle_range_reservation_is_uncommitted_and_rollback_safe(reference_db):
    db = reference_db
    commits = []
    event.listen(db, "after_commit", lambda *_: commits.append(True))
    assert bundles_service.reserve_bundle_numbers(db, 3) == ["BND-0001", "BND-0002", "BND-0003"]
    assert [(r.reference, r.canonical_reference, r.entity_id) for r in db.query(BusinessOrderAlias).order_by(BusinessOrderAlias.id)] == [
        ("BND-0001", "BND-0001", 0),
        ("BND-0002", "BND-0002", 0),
        ("BND-0003", "BND-0003", 0),
    ]
    assert commits == []
    db.rollback()
    assert db.query(BusinessOrderAlias).count() == 0


def test_package_approval_notifications_share_outer_transaction(reference_db, monkeypatch):
    db = reference_db
    db.add_all([
        User(name="Approver", email="support-approver@example.test", password_hash="test"),
        User(name="Requester", email="support-requester@example.test", password_hash="test"),
    ])
    db.flush()
    approver, requester = db.query(User).order_by(User.id).all()
    monkeypatch.setattr(packages_service, "_is_package_change_approver", lambda user: user.id == approver.id)
    commits = []
    event.listen(db, "after_commit", lambda *_: commits.append(True))
    request = SimpleNamespace(requested_by=requester.id)
    assert packages_service._notify_package_change_approvers(
        db, request=request, package_no="PKG-TEST", request_type="edit", exclude_user_id=requester.id,
    ) == 1
    packages_service._notify_package_requester(db, request=request, title="Approved", message="Request accepted")
    db.flush()
    assert [(n.user_id, n.title, n.message, n.link) for n in db.query(Notification).order_by(Notification.id)] == [
        (approver.id, "Package edit approval needed", "PKG-TEST has a pending edit request.", "/packages"),
        (requester.id, "Approved", "Request accepted", "/packages"),
    ]
    assert commits == []
    db.rollback()
    assert db.query(Notification).count() == 0


def test_employee_alias_setting_joins_reconciliation_transaction(reference_db):
    db = reference_db
    db.add_all([
        Employee(full_name="Aliyeva Mushtariy", employee_no="322", factory_code="MIL"),
        Employee(full_name="Same Person", employee_no="7011", factory_code="MIL"),
        Employee(full_name="Same Person", employee_no="7012", factory_code="MIL"),
    ])
    db.flush()
    manager, target, source = db.query(Employee).order_by(Employee.id).all()
    commits = []
    event.listen(db, "after_commit", lambda *_: commits.append(True))
    reconcile_employees(db, {
        "names": [], "report_manager": manager.id,
        "merges": [{"source": source.id, "target": target.id, "factory": "MIL",
                    "name": "Same Person", "source_no": "7012", "target_no": "7011"}],
    })
    setting = db.query(SystemSetting).filter_by(key="employee_merge_aliases:MIL").one()
    assert setting.value_json == {
        "ids": {str(source.id): target.id}, "numbers": {"7012": target.id},
    }
    assert commits == []
    db.rollback()
    assert db.query(SystemSetting).filter_by(key="employee_merge_aliases:MIL").count() == 0
