"""Independent typed seams; parameter spelling is not a business contract."""
from inspect import signature
from typing import get_type_hints

from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestIn
from app.libs.dto.purchasing.purchase_request_output import PurchaseRequestOut
from app.libs.enums.purchasing import PurchaseRequestStatus
from app.libs.types.purchasing import PurchaseRequestCreateCommand
from app.models import purchasing_service
from app.models.purchasing.requests_service import _purchase_request_command
from app.schemas.purchasing.purchase_request_persistence import add_purchase_request_row


def test_input_and_output_annotations_and_required_output():
    assert PurchaseRequestIn.model_fields['status'].annotation is PurchaseRequestStatus
    field = PurchaseRequestOut.model_fields['status']
    assert field.annotation is PurchaseRequestStatus
    assert field.is_required()


def test_used_internal_command_preserves_enum_member_and_wire_value():
    assert get_type_hints(PurchaseRequestCreateCommand)['status'] is PurchaseRequestStatus
    assert get_type_hints(purchasing_service.create_purchase_request)['data'] is PurchaseRequestCreateCommand
    payload = PurchaseRequestIn(lines=[{'item_id': 1}])
    command = _purchase_request_command(payload)
    assert command['status'] is PurchaseRequestStatus.PENDING_APPROVAL
    assert payload.model_dump(mode='json')['status'] == 'pending_approval'


def test_internal_creation_guard_preserves_canonical_enum():
    guard = purchasing_service._create_request_status
    parameters = list(signature(guard).parameters)
    assert len(parameters) == 1
    hints = get_type_hints(guard)
    assert hints[parameters[0]] is PurchaseRequestStatus
    assert hints['return'] is PurchaseRequestStatus


def test_schema_writer_takes_canonical_enum_until_storage_assignment():
    assert get_type_hints(add_purchase_request_row)['status'] is PurchaseRequestStatus
