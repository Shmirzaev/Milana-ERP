from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.libs.dto.work_management.tasks import TaskIn, TaskOut, TaskUpdate
from app.libs.enums.work_management import TaskPriority, TaskStatus


def test_task_fixed_vocabularies_are_canonical_across_input_update_and_output():
    created = TaskIn.model_validate({"title": "Typed task", "status": "in_progress", "priority": "urgent"})
    updated = TaskUpdate.model_validate({"status": "completed", "priority": "high"})

    assert created.status is TaskStatus.IN_PROGRESS
    assert created.priority is TaskPriority.URGENT
    assert TaskIn.model_fields["status"].annotation is TaskStatus
    assert TaskIn.model_fields["priority"].annotation is TaskPriority
    assert TaskUpdate.model_fields["status"].annotation == TaskStatus | None
    assert TaskUpdate.model_fields["priority"].annotation == TaskPriority | None

    output = TaskOut.model_validate({
        "id": 7,
        "title": "Typed task",
        "status": "completed",
        "priority": "high",
        "created_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    })
    assert output.status is TaskStatus.COMPLETED
    assert output.priority is TaskPriority.HIGH
    assert output.model_dump(mode="json")["status"] == "completed"
    assert output.model_dump(mode="json")["priority"] == "high"


@pytest.mark.parametrize("field,value", [("status", "done-ish"), ("priority", "critical")])
def test_task_create_and_update_reject_unknown_fixed_vocabulary(field, value):
    with pytest.raises(ValidationError):
        TaskIn.model_validate({"title": "Invalid", field: value})
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({field: value})


def test_task_creation_defaults_remain_canonical_values():
    payload = TaskIn.model_validate({"title": "Default values"})
    assert payload.status is TaskStatus.PENDING
    assert payload.priority is TaskPriority.MEDIUM
