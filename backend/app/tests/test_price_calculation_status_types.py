from datetime import datetime, timezone
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from app.libs.dto.planning.price_calculation_request_output import PriceCalculationRequestOut
from app.libs.enums.planning import PriceCalculationStatus as Status
from app.models import price_calculation_service as pricing


def request(**changes):
    fields = dict(kroy_no=None, fabric_width_m=None, lay_length_m=None, size_count=None,
                  gramage=None, binding_kg_per_piece=None, fabric_price=None, sewing_cost=None,
                  accessories_json=[], selling_price=None)
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(('values', 'expected'), [
    ([False, False], Status.NEW), ([True, False], Status.IN_PROGRESS),
    ([True, True], Status.COMPLETE), ([], Status.NEW),
])
def test_stage_matrix(values, expected):
    assert pricing._stage_status(values) is expected


def test_statuses_and_overall_preserve_completion_rules():
    row = request()
    assert pricing.cutting_status(row) is Status.NEW
    assert pricing.purchasing_status(row) is Status.NEW
    assert pricing.accessories_status(row) is Status.NEW
    assert pricing.overall_status(row) is Status.NEW
    row.kroy_no = ' K '
    assert pricing.cutting_status(row) is Status.IN_PROGRESS
    row.fabric_width_m, row.lay_length_m, row.size_count, row.gramage = 1, 2, 3, 4
    row.binding_kg_per_piece = 0  # zero is deliberately valid here
    row.fabric_price, row.sewing_cost = 1, 2
    row.accessories_json = [{'name': 'button', 'price': 0}]
    assert pricing.accessories_status(row) is Status.IN_PROGRESS
    row.accessories_json[0]['price'] = 1
    assert pricing.cutting_status(row) is Status.COMPLETE
    assert pricing.purchasing_status(row) is Status.COMPLETE
    assert pricing.accessories_status(row) is Status.COMPLETE
    assert pricing.overall_status(row) is Status.IN_PROGRESS
    row.selling_price = 1
    assert pricing.overall_status(row) is Status.COMPLETE
    row.accessories_json = [None, {}, {'name': ' ', 'price': None}]
    assert pricing.accessories_status(row) is Status.NEW


def test_output_enum_identity_json_and_openapi():
    names = ('cutting_status', 'purchasing_status', 'accessories_status', 'overall_status')
    assert all(get_type_hints(PriceCalculationRequestOut)[name] is Status for name in names)
    dto = PriceCalculationRequestOut(id=1, model_id=1, model_no='M', variant_no='V',
        model_name='model', packaging_cost=0.1, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc), **dict.fromkeys(names, 'new'))
    assert all(getattr(dto, name) is Status.NEW for name in names)
    assert all(dto.model_dump(mode='json')[name] == 'new' for name in names)
    schema = PriceCalculationRequestOut.model_json_schema()
    assert schema['$defs']['PriceCalculationStatus']['enum'] == ['new', 'in_progress', 'complete']
    assert all(schema['properties'][name]['$ref'] == '#/$defs/PriceCalculationStatus' for name in names)


@pytest.mark.parametrize(('fabric', 'sewing', 'expected'), [
    (None, None, Status.NEW), (0, 0, Status.NEW), (1, 0, Status.IN_PROGRESS),
    (0, 1, Status.IN_PROGRESS), (1, 1, Status.COMPLETE),
])
def test_purchasing_zero_and_partial_values(fabric, sewing, expected):
    assert pricing.purchasing_status(request(fabric_price=fabric, sewing_cost=sewing)) is expected


@pytest.mark.parametrize(('rows', 'expected'), [
    ([], Status.NEW), ([{'name': '  ', 'price': None}], Status.NEW),
    ([{'name': None, 'price': 1}], Status.IN_PROGRESS),
    ([{'name': 'button', 'price': 0}], Status.IN_PROGRESS),
    ([{'name': 'button', 'price': 1}, {'name': 'zip', 'price': None}], Status.IN_PROGRESS),
    ([{'name': 'button', 'price': 1}], Status.COMPLETE),
])
def test_accessory_empty_incomplete_and_complete_rows(rows, expected):
    assert pricing.accessories_status(request(accessories_json=rows)) is expected


def test_cutting_zero_binding_is_present_but_zero_dimensions_are_not():
    row = request(kroy_no='K', fabric_width_m=1, lay_length_m=1, size_count=1,
                  gramage=1, binding_kg_per_piece=0)
    assert pricing.cutting_status(row) is Status.COMPLETE
    row.fabric_width_m = 0
    assert pricing.cutting_status(row) is Status.IN_PROGRESS
    row.fabric_width_m = 1
    row.binding_kg_per_piece = None
    assert pricing.cutting_status(row) is Status.IN_PROGRESS
