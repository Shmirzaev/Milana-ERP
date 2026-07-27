from app.api.routes.process_tracking import _actual_output_quantity


def test_actual_output_quantity_uses_highest_verified_stage_output():
    stages = [
        {"operation": "cutting", "completed": 612},
        {"operation": "sewing", "completed": 620},
        {"operation": "packaging", "completed": 620},
        {"operation": "storage_transfer", "completed": 0},
    ]

    assert _actual_output_quantity(stages) == 620


def test_actual_output_quantity_is_zero_before_production_starts():
    assert _actual_output_quantity([]) == 0
    assert _actual_output_quantity([{"operation": "cutting", "completed": None}]) == 0
