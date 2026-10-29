"""Contract checks for the Inventory batch edit write boundary."""

import ast
import inspect

from app.models.inventory import stock_service
from app.schemas.inventory import stock_batch_persistence


def test_update_batch_delegates_patch_and_ledger_writes_to_schema_operation():
    source = inspect.getsource(stock_service.update_batch)
    assert "stock_batch_persistence.apply_batch_edit(" in source
    assert "setattr(batch" not in source
    assert "db.add(StockMovement" not in source


def test_schema_batch_edit_uses_session_without_owning_transaction_or_policy():
    tree = ast.parse(inspect.getsource(stock_batch_persistence))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    called_methods = {node.func.attr for node in calls if isinstance(node.func, ast.Attribute)}
    assert "commit" not in called_methods
    assert "rollback" not in called_methods
    assert "add" in called_methods
    assert "update" in called_methods


def test_batch_edit_preserves_explicit_null_and_omitted_patch_values():
    # The service hands the schema operation only model_dump(exclude_unset=True),
    # preserving the DTO distinction between an omitted field and explicit null.
    source = inspect.getsource(stock_service.update_batch)
    assert "payload.model_dump(exclude_unset=True)" in source
    operation_source = inspect.getsource(stock_batch_persistence.apply_batch_edit)
    assert "for key, value in command.values.items()" in operation_source
