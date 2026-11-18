"""Run one whole-module shard of the default backend pytest regression suite."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


PYTEST_ARGS = ("-q", "--ignore=app/tests/test_readiness_operation_characterization.py", "--durations=25")
SHA256 = re.compile(r"[0-9a-f]{64}")
OUTCOMES = ("passed", "skipped")


def partition_nodes(nodeids: list[str], count: int) -> list[list[str]]:
    """Balance by collected cases while keeping each module's fixtures together."""
    if count < 1 or len(nodeids) != len(set(nodeids)):
        raise ValueError("Expected a positive shard count and unique collected pytest IDs")

    def module(nodeid: str) -> str:
        return nodeid.partition("::")[0]

    sizes = Counter(map(module, nodeids))
    if len(sizes) < count:
        raise ValueError(f"Only {len(sizes)} collected test modules for {count} shards")

    loads = [0] * count
    owners = {}
    for path, size in sorted(sizes.items(), key=lambda entry: (-entry[1], entry[0])):
        index = min(range(count), key=loads.__getitem__)
        owners[path] = index
        loads[index] += size

    shards: list[list[str]] = [[] for _ in range(count)]
    for nodeid in nodeids:
        shards[owners[module(nodeid)]].append(nodeid)
    return shards


def node_digest(nodeid: str) -> str:
    return hashlib.sha256(nodeid.encode("utf-8", errors="surrogatepass")).hexdigest()


def collection_digest(digests) -> str:
    canonical = "\n".join(sorted(digests)).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def run_shard(index: int, count: int, manifest: Path) -> int:
    import pytest

    if not 1 <= index <= count:
        raise ValueError("Shard index must be between 1 and the shard count")
    manifest.unlink(missing_ok=True)

    class Shard:
        def __init__(self):
            self.nodeids = []
            self.selected = []
            self.outcomes = {}

        @pytest.hookimpl(wrapper=True, tryfirst=True)
        def pytest_collection_modifyitems(self, config, items):
            yield
            # Wait for ordinary pytest selectors to finish before partitioning.
            self.nodeids = [item.nodeid for item in items]
            try:
                self.selected = partition_nodes(self.nodeids, count)[index - 1]
            except ValueError as error:
                raise pytest.UsageError(str(error)) from error
            selected = set(self.selected)
            deselected = [item for item in items if item.nodeid not in selected]
            config.hook.pytest_deselected(items=deselected)
            items[:] = [item for item in items if item.nodeid in selected]

        def pytest_runtest_logreport(self, report):
            # Pytest reports each subtest under its parent's ID. Only the
            # parent's result belongs in the collection receipt.
            if type(report) is not pytest.TestReport:
                return
            # An intentional setup skip has no call report. Pytest's own exit
            # code covers failed setup, teardown, collection and interrupted runs.
            if report.when == "call" or (report.when == "setup" and report.skipped):
                if report.nodeid in self.outcomes:
                    raise RuntimeError("Received multiple outcomes for one pytest ID")
                self.outcomes[report.nodeid] = report.outcome

    shard = Shard()
    exit_code = pytest.main(list(PYTEST_ARGS), plugins=[shard])
    if exit_code != pytest.ExitCode.OK:
        return int(exit_code)
    if not shard.selected or set(shard.selected) != set(shard.outcomes) or set(shard.outcomes.values()) - set(OUTCOMES):
        raise ValueError("Pytest outcomes do not match the selected tests")

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "version": 1,
        "index": index,
        "count": count,
        "collection_count": len(shard.nodeids),
        "collection_sha256": collection_digest(map(node_digest, shard.nodeids)),
        "results": [
            {"node_sha256": node_digest(nodeid), "outcome": shard.outcomes[nodeid]}
            for nodeid in shard.selected
        ],
    }, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Shard {index}/{count} recorded {len(shard.selected)} of {len(shard.nodeids)} collected tests")
    return 0


def verify_shards(count: int, directory: Path) -> None:
    if count < 1:
        raise ValueError("Expected a positive shard count")
    paths = sorted(directory.glob("backend-regression-*/backend-shard.json"))
    if len(paths) != count:
        raise ValueError(f"Expected {count} shard manifests, found {len(paths)}")

    indices = set()
    results = {}
    collection = None
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("count") != count:
            raise ValueError(f"Invalid manifest version or shard count: {path}")
        index = manifest.get("index")
        if type(index) is not int or not 1 <= index <= count or index in indices:
            raise ValueError(f"Invalid or duplicate shard index: {path}")
        indices.add(index)
        size, digest = manifest.get("collection_count"), manifest.get("collection_sha256")
        if type(size) is not int or size < count or not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise ValueError(f"Invalid full collection count or hash: {path}")
        if collection is None:
            collection = (size, digest)
        elif collection != (size, digest):
            raise ValueError(f"Shards collected different pytest suites: {path}")

        rows = manifest.get("results")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Missing shard test results: {path}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Invalid test result: {path}")
            key, outcome = row.get("node_sha256"), row.get("outcome")
            if not isinstance(key, str) or SHA256.fullmatch(key) is None or outcome not in OUTCOMES:
                raise ValueError(f"Invalid result digest or outcome: {path}")
            if key in results:
                raise ValueError(f"Duplicate test within or across shards: {path}")
            results[key] = outcome

    if collection != (len(results), collection_digest(results)):
        raise ValueError("Combined shard results do not match the full pytest collection")
    totals = Counter(results.values())
    print(f"Verified {count} shards and {len(results)} tests ({totals['passed']} passed, {totals['skipped']} skipped)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one shard from the backend directory")
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify manifests downloaded from every shard")
    verify.add_argument("--count", type=int, required=True)
    verify.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "run":
            return run_shard(args.index, args.count, args.manifest)
        verify_shards(args.count, args.directory)
    except (OSError, ValueError) as error:
        print(f"Backend regression shards: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
