"""Independent checks for Sales canonical input/output enum adoption."""
from typing import get_args

import pytest

from app.libs.dto.sales.sales_order_input import SalesOrderIn, SalesOrderItemIn
from app.libs.dto.sales.sales_order_output import SalesOrderOut, SalesOrderItemOut
from app.libs.enums.sales import SalesOrderType, SalesOrderItemSourceType, SalesOrderStatus


@pytest.mark.parametrize('model, field, expected', [
    (SalesOrderIn, 'order_type', SalesOrderType),
    (SalesOrderItemIn, 'source_type', SalesOrderItemSourceType),
    (SalesOrderOut, 'order_type', SalesOrderType),
    (SalesOrderOut, 'status', SalesOrderStatus),
    (SalesOrderItemOut, 'source_type', SalesOrderItemSourceType),
])
def test_actual_contract_annotation_is_canonical_enum(model, field, expected):
    assert model.model_fields[field].annotation is expected


def test_default_order_type_is_a_member_and_serializes_as_the_wire_value():
    value = SalesOrderIn(items=[])
    assert value.order_type is SalesOrderType.CLIENT_ORDER
    assert value.model_dump(mode='json')['order_type'] == 'client_order'


def test_default_line_source_is_a_member_and_serializes_as_the_wire_value():
    value = SalesOrderItemIn(model_id=1, color='white', size='M', quantity=3)
    assert value.source_type is SalesOrderItemSourceType.PRODUCE_NEW
    assert value.model_dump(mode='json')['source_type'] == 'produce_new'
