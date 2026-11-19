"""The policy leaf breaks the factory-context/user-access dependency cycle."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND = Path(__file__).resolve().parents[2]
MODULES = (
    "app.models.factory_scope_service",
    "app.models.user_access_service",
    "app.models.identity.access_policy_service",
    "app.core.permission_catalog",
)


def test_factory_scope_import_does_not_load_user_access():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.models.factory_scope_service; "
         "assert 'app.models.user_access_service' not in sys.modules"],
        cwd=BACKEND, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["policy_for", "denied_for", "apply_policy"])
def test_legacy_policy_exports_are_the_leaf_functions(name):
    from app.models import factory_scope_service, user_access_service
    from app.models.identity import access_policy_service

    function = getattr(access_policy_service, name)
    assert getattr(user_access_service, name) is function
    assert getattr(factory_scope_service, name) is function


def test_policy_import_graph_has_no_cycle_including_function_local_imports():
    graph = {}
    for module in MODULES:
        path = BACKEND.joinpath(*module.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        dependencies = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.")
        }
        if module == "app.models.identity.access_policy_service":
            assert dependencies == {"app.core.permission_catalog"}
        graph[module] = dependencies.intersection(MODULES)

    def visit(module, ancestors):
        assert module not in ancestors, f"Import cycle: {(*ancestors, module)}"
        for dependency in graph[module]:
            visit(dependency, (*ancestors, module))

    for module in MODULES:
        visit(module, ())
