"""Current Work contracts on SQLite and isolated PostgreSQL."""
from datetime import datetime, timezone
from uuid import uuid4

from app.libs.dto.work_management.tasks import TaskOut
from app.models.work_management.tasks_service import _task_link, resolve_task_reference
from app.schemas import Shipment, Task, User
from app.schemas.work_management.task_persistence import complete_task_row
from app.tests.test_task_broadcast_batching import broadcast_sessions as broadcast_sessions


def test_task_reference_and_completion_keep_stored_and_output_values(broadcast_sessions):
    with broadcast_sessions() as db:
        marker = uuid4().hex
        actor = User(name="Work contract actor", email=f"{marker}@example.invalid",
                     password_hash="unused", extra_permissions=["tasks.manage"])
        shipment = Shipment(shipment_no=f"SH-WORK-{marker[:10]}")
        db.add_all((actor, shipment))
        db.flush()
        task = Task(title="Work contract", created_by=actor.id, assigned_to=actor.id,
                    status="pending", priority="medium", entity_type="Shipments",
                    entity_id=shipment.id)
        db.add(task)
        db.commit()

        reference = resolve_task_reference(db, actor, "Shipments", shipment.id)
        assert reference is not None and reference.key == "shipment"
        assert _task_link(task, reference=reference) == "/shipments"
        assert TaskOut.model_validate(task).model_dump(mode="json")["status"] == "pending"

        completed_at = datetime.now(timezone.utc)
        complete_task_row(db, task, completed_at=completed_at)
        db.commit()
        db.refresh(task)
        output = TaskOut.model_validate(task).model_dump(mode="json")
        assert task.status == output["status"] == "completed"
        assert task.priority == output["priority"] == "medium"
        assert task.completed_at is not None


def test_legacy_task_strings_still_serialize_without_reclassification(broadcast_sessions):
    with broadcast_sessions() as db:
        task = Task(title=f"Legacy {uuid4().hex}", status="legacy_status",
                    priority="legacy_priority")
        db.add(task)
        db.commit()
        output = TaskOut.model_validate(task).model_dump(mode="json")
        assert (output["status"], output["priority"]) == ("legacy_status", "legacy_priority")
