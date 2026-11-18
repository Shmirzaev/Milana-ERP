"""Partition a collected suite by file; each hosted runner owns its databases."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--ci-shard", type=int, default=0)
    parser.addoption("--ci-shards", type=int, default=1)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    index = config.getoption("--ci-shard")
    count = config.getoption("--ci-shards")
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError("Require --ci-shards >= 1 and 0 <= --ci-shard < --ci-shards")
    groups = {}
    for item in items:
        groups.setdefault(item.nodeid.split("::", 1)[0], []).append(item)
    loads = [0] * count
    selected = set()
    # Largest files first reduces skew without splitting module-scoped fixtures.
    for path, group in sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0])):
        owner = min(range(count), key=lambda shard: (loads[shard], shard))
        loads[owner] += len(group)
        if owner == index:
            selected.add(path)
    retained, removed = [], []
    for item in items:
        (retained if item.nodeid.split("::", 1)[0] in selected else removed).append(item)
    items[:] = retained
    config.hook.pytest_deselected(items=removed)
    print(f"CI shard {index + 1}/{count}: {len(retained)} of {sum(loads)} collected tests")
