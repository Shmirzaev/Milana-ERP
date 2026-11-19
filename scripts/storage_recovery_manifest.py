"""Create and verify a read-only inventory pairing a PostgreSQL dump with storage files.

The manifest does not take a backup. Operators must quiesce writes and create
both artifacts with their approved backup tools before creating the pairing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


FORMAT = "milana-storage-recovery-manifest-v1"
CHUNK_SIZE = 1024 * 1024
URL_ROOTS = {
    "model-files": "model_files",
    "sales-order-files": "sales_order_files",
    "barcodes": "barcodes",
}
# Only active file-bearing columns: audit/history text can mention deleted files.
REFERENCE_COLUMNS = {
    "brands": {"logo_url": "url"},
    "model_images": {"file_url": "url"},
    "model_bom": {"photo_url": "url"},
    "items": {"image_url": "url"},
    "stock_batches": {"image_url": "url"},
    "waste_disposal_requests": {"proof_file_url": "url"},
    "purchase_request_lines": {"photo_url": "url"},
    "purchase_order_lines": {"photo_url": "url"},
    "sales_orders": {"printing_attachments": "json"},
    "production_orders": {"printing_attachments": "json"},
    "system_settings": {"value_json": "json"},
    "cutting_passports": {"image_ref": "url"},
    "bundles": {"qr_code_url": "url"},
    "packages": {"qr_code_url": "url"},
    "hr_employee_documents": {"stored_name": "hr_documents"},
    "attendance_people": {"photo_file_name": "attendance_photos"},
}
COPY_HEADER = re.compile(r'^COPY (?:"?[a-z_]+"?\.)?"?([a-z_]+)"? \(([^)]+)\) FROM stdin;$')
COPY_ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|[0-7]{1,3}|.)")


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


def _unescape_copy(value: str) -> str | None:
    if value == r"\N":
        return None

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("x"):
            return chr(int(token[1:], 16))
        if token[0] in "01234567":
            return chr(int(token, 8))
        return {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}.get(token, token)

    return COPY_ESCAPE.sub(replace, value)


def _local_url_path(value: str) -> str | None:
    if not value.startswith("/storage/"):
        return None  # External URLs do not belong to /app/storage.
    parts = unquote(urlsplit(value).path).split("/")
    if len(parts) < 4 or any(part in {"", ".", ".."} or "\\" in part for part in parts[2:]):
        raise ValueError(f"unsafe stored upload URL: {value}")
    root = URL_ROOTS.get(parts[2])
    if root is None:
        raise ValueError(f"unknown local storage URL root: {value}")
    return "/".join((root, *parts[3:]))


def _stored_name_path(root: str, value: str) -> str:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"unsafe stored upload filename in {root}: {value}")
    return f"{root}/{value}"


def _json_urls(value: Any):
    if isinstance(value, str):
        path = _local_url_path(value)
        if path:
            yield path
    elif isinstance(value, list):
        for item in value:
            yield from _json_urls(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_urls(item)


def database_file_references(database_dump: Path) -> list[str]:
    """Read known file columns from a custom pg_dump archive; never restore or connect."""
    command = ["pg_restore", "--data-only", "--no-owner", "--no-privileges", "--file=-"]
    for table in REFERENCE_COLUMNS:
        command.extend(("--table", table))
    result = subprocess.run([*command, str(database_dump)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"pg_restore could not read the database dump: {result.stderr.strip()}")
    references: set[str] = set()
    seen: set[str] = set()
    table = None
    indexes: dict[str, int] = {}
    for line in result.stdout.splitlines():
        match = COPY_HEADER.fullmatch(line)
        if match:
            table = match.group(1)
            if table in REFERENCE_COLUMNS:
                seen.add(table)
                columns = [part.strip().strip('"') for part in match.group(2).split(",")]
                indexes = {column: columns.index(column) for column in REFERENCE_COLUMNS[table] if column in columns}
                if len(indexes) != len(REFERENCE_COLUMNS[table]):
                    raise ValueError(f"database dump lacks expected upload columns in {table}")
            continue
        if line == r"\.":
            table = None
            continue
        if table not in REFERENCE_COLUMNS or not indexes:
            continue
        values = line.split("\t")
        for column, kind in REFERENCE_COLUMNS[table].items():
            if indexes[column] >= len(values):
                raise ValueError(f"malformed COPY row in {table}")
            value = _unescape_copy(values[indexes[column]])
            if value is None:
                continue
            if kind == "url":
                path = _local_url_path(value)
                if path:
                    references.add(path)
            elif kind == "json":
                references.update(_json_urls(json.loads(value)))
            else:
                references.add(_stored_name_path(kind, value))
    missing_tables = sorted(set(REFERENCE_COLUMNS) - seen)
    if missing_tables:
        raise ValueError(f"database dump lacks upload table data: {', '.join(missing_tables)}")
    return sorted(references)


def create_manifest(database_dump: Path, storage_root: Path, *, allow_missing_references: bool = False) -> dict[str, Any]:
    if database_dump.is_symlink():
        raise ValueError("database dump cannot be a symbolic link")
    database_dump = database_dump.resolve(strict=True)
    if not database_dump.is_file():
        raise ValueError("database dump must be a regular file")
    dump_hash, dump_size = sha256_file(database_dump)
    if dump_size == 0:
        raise ValueError("database dump is empty")
    files = storage_inventory(storage_root)
    references = database_file_references(database_dump)
    if sha256_file(database_dump) != (dump_hash, dump_size):
        raise ValueError("database dump changed during verification")
    missing = sorted(set(references) - files.keys())
    if missing and not allow_missing_references:
        raise ValueError(f"database references files absent from storage snapshot: {', '.join(missing)}")
    return {
        "format": FORMAT,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database_dump": {"size_bytes": dump_size, "sha256": dump_hash},
        "storage_root_label": "/app/storage",
        "storage_files": files,
        "database_references": references,
    }


def _validate_manifest(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError("unsupported or malformed manifest")
    database_dump = document.get("database_dump")
    files = document.get("storage_files")
    references = document.get("database_references")
    if not isinstance(database_dump, dict) or not isinstance(files, dict) or not isinstance(references, list):
        raise ValueError("manifest is missing database_dump, storage_files or database_references")
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
            or relative.as_posix() != name
            or ".." in relative.parts
            or "\\" in name
            or not isinstance(item, dict)
            or not isinstance(item.get("size_bytes"), int)
            or item["size_bytes"] < 0
            or not _is_sha256(item.get("sha256"))
        ):
            raise ValueError("manifest contains an invalid storage entry")
    if any(not isinstance(name, str) or name not in files for name in references):
        raise ValueError("manifest contains a reference absent from its storage inventory")
    return document


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def verify_manifest(manifest_path: Path, database_dump: Path, storage_root: Path) -> dict[str, Any]:
    document = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    actual = create_manifest(database_dump, storage_root, allow_missing_references=True)
    expected_files = document["storage_files"]
    actual_files = actual["storage_files"]
    expected_names, actual_names = set(expected_files), set(actual_files)
    changed = sorted(name for name in expected_names & actual_names if expected_files[name] != actual_files[name])
    expected_db, actual_db = document["database_dump"], actual["database_dump"]
    database_matches = expected_db == actual_db
    missing_referenced = sorted(set(actual["database_references"]) - actual_names)
    references_match = document["database_references"] == actual["database_references"]
    result = {
        "ok": database_matches and references_match and not missing_referenced and not changed and expected_names == actual_names,
        "database_dump_matches": database_matches,
        "database_references_match": references_match,
        "missing_referenced_files": missing_referenced,
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
                    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
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
