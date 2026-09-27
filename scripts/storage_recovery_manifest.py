"""Create and verify a read-only inventory pairing a PostgreSQL dump with storage files.

The manifest does not take a backup. Operators must quiesce writes and create
both artifacts with their approved backup tools before creating the pairing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


FORMAT = "milana-storage-recovery-manifest-v1"
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def storage_inventory(root: Path) -> dict[str, dict[str, Any]]:
    """Hash every regular file without following links or changing the tree."""
    if root.is_symlink():
        raise ValueError("storage root cannot be a symbolic link")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("storage root must be a directory")

    inventory: dict[str, dict[str, Any]] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"symbolic links are not supported: {path.relative_to(root).as_posix()}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    relative = path.relative_to(root).as_posix()
                    digest, size = sha256_file(path)
                    inventory[relative] = {"size_bytes": size, "sha256": digest}
                else:
                    raise ValueError(f"non-regular storage entry is not supported: {path.relative_to(root).as_posix()}")
    return dict(sorted(inventory.items()))


def create_manifest(database_dump: Path, storage_root: Path) -> dict[str, Any]:
    if database_dump.is_symlink():
        raise ValueError("database dump cannot be a symbolic link")
    database_dump = database_dump.resolve(strict=True)
    if not database_dump.is_file():
        raise ValueError("database dump must be a regular file")
    dump_hash, dump_size = sha256_file(database_dump)
    if dump_size == 0:
        raise ValueError("database dump is empty")
    return {
        "format": FORMAT,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database_dump": {"size_bytes": dump_size, "sha256": dump_hash},
        "storage_root_label": "/app/storage",
        "storage_files": storage_inventory(storage_root),
    }


def _validate_manifest(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError("unsupported or malformed manifest")
    database_dump = document.get("database_dump")
    files = document.get("storage_files")
    if not isinstance(database_dump, dict) or not isinstance(files, dict):
        raise ValueError("manifest is missing database_dump or storage_files")
    if (
        not isinstance(database_dump.get("size_bytes"), int)
        or database_dump["size_bytes"] <= 0
        or not _is_sha256(database_dump.get("sha256"))
    ):
        raise ValueError("manifest contains invalid database dump metadata")
    for name, item in files.items():
        if not isinstance(name, str):
            raise ValueError("manifest contains an invalid storage entry")
        relative = PurePosixPath(name)
        if (
            not name
            or relative.is_absolute()
            or ".." in relative.parts
            or "\\" in name
            or not isinstance(item, dict)
            or not isinstance(item.get("size_bytes"), int)
            or item["size_bytes"] < 0
            or not _is_sha256(item.get("sha256"))
        ):
            raise ValueError("manifest contains an invalid storage entry")
    return document


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def verify_manifest(manifest_path: Path, database_dump: Path, storage_root: Path) -> dict[str, Any]:
    document = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    actual = create_manifest(database_dump, storage_root)
    expected_files = document["storage_files"]
    actual_files = actual["storage_files"]
    expected_names, actual_names = set(expected_files), set(actual_files)
    changed = sorted(name for name in expected_names & actual_names if expected_files[name] != actual_files[name])
    expected_db, actual_db = document["database_dump"], actual["database_dump"]
    database_matches = expected_db == actual_db
    result = {
        "ok": database_matches and not changed and expected_names == actual_names,
        "database_dump_matches": database_matches,
        "storage_file_count_expected": len(expected_names),
        "storage_file_count_actual": len(actual_names),
        "missing_files": sorted(expected_names - actual_names),
        "extra_files": sorted(actual_names - expected_names),
        "changed_files": changed,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="hash the supplied dump and storage snapshot")
    create.add_argument("--database-dump", type=Path, required=True)
    create.add_argument("--storage-root", type=Path, required=True)
    create.add_argument("--output", type=Path, help="write manifest here; omit to print JSON to stdout")
    verify = commands.add_parser("verify", help="compare supplied artifacts to a saved manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--database-dump", type=Path, required=True)
    verify.add_argument("--storage-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "create":
            result = create_manifest(args.database_dump, args.storage_root)
            rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
            if args.output:
                output = args.output.resolve()
                storage = args.storage_root.resolve(strict=True)
                dump = args.database_dump.resolve(strict=True)
                if output == dump or storage == output or storage in output.parents:
                    raise ValueError("manifest output must be outside the dump and storage tree")
                try:
                    with output.open("x", encoding="utf-8") as stream:
                        stream.write(rendered)
                except FileExistsError as exc:
                    raise ValueError("manifest output already exists; choose a new path") from exc
            else:
                sys.stdout.write(rendered)
            return 0

        result = verify_manifest(args.manifest, args.database_dump, args.storage_root)
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0 if result["ok"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"storage recovery manifest: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
