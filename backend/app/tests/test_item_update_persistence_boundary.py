from decimal import Decimal

from sqlalchemy import event

from app.libs.types.inventory import ItemUpdateCommand
from app.schemas import Item
from app.schemas.inventory.item_persistence import update_item


def test_update_assigns_every_field_in_order_even_when_unchanged_without_session_io():
    values = dict(
        sku='S', name='Name', category='fabric', unit='kg', default_cost=Decimal('1'),
        reorder_level=Decimal('2'), track_batch=True, is_active=True, image_url=None,
        composition_json=[{'name': 'Cotton', 'percentage': 100.0}],
    )
    item = Item(**values)
    seen = []
    def on_set(target, value, oldvalue, initiator):
        seen.append((initiator.key, value))
    listeners = [getattr(Item, field) for field in values]
    for attribute in listeners:
        event.listen(attribute, 'set', on_set)
    class NoSessionIO:
        def __getattr__(self, name):
            raise AssertionError(f'unexpected Session access: {name}')
    try:
        assert update_item(NoSessionIO(), item, ItemUpdateCommand(**values)) is item
    finally:
        for attribute in listeners:
            event.remove(attribute, 'set', on_set)
    assert seen == list(values.items())


def test_update_command_tracks_normalized_dto_field_set_and_order():
    from dataclasses import fields

    from app.libs.dto.inventory.item_input import ItemIn
    from app.models.inventory.stock_service import _item_payload

    expected = ['sku', 'name', 'category', 'unit', 'default_cost', 'reorder_level',
                'track_batch', 'is_active', 'image_url', 'composition_json']
    payload = ItemIn(sku='S', name='Name', category='fabric', unit='kg')
    assert list(_item_payload(payload)) == expected
    assert [field.name for field in fields(ItemUpdateCommand)] == expected
