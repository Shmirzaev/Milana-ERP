from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.api.routes.packages import (
    _batch_allocations_html,
    _package_label_card_html,
    _size_breakdown_html,
)


def test_package_label_shows_sizes_without_piece_counts():
    package = SimpleNamespace(
        items=[
            SimpleNamespace(size="M-46", quantity=12),
            SimpleNamespace(size="L-48", quantity=48),
        ],
        batch_allocations=[SimpleNamespace(production_batch_id=7, quantity=60)],
        production_batch_id=None,
        total_quantity=60,
    )

    size_html = _size_breakdown_html(package)
    assert "M-46" in size_html
    assert "L-48" in size_html
    assert ">12<" not in size_html
    assert ">48<" not in size_html
    assert "<em>" not in size_html

    class FakeDb:
        @staticmethod
        def get(_model, row_id):
            assert row_id == 7
            return SimpleNamespace(batch_no="0075-01", name="Batch 1")

    batch_html = _batch_allocations_html(FakeDb(), package)
    assert batch_html == "0075-01 - Batch 1"
    assert ": 60" not in batch_html

    card_source = inspect.getsource(_package_label_card_html)
    assert "<th>Size</th>" in card_source
    assert "Size / quantity" not in card_source
    assert "<th>Quantity</th>" not in card_source
