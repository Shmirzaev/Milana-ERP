"""Archive verified source and prune inactive production release directories.

Dry-run is the default. Deletion requires both --apply and an exact hostname
confirmation. Active, rollback, newest retained releases, and releases without
a valid source manifest are never removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import tarfile
from pathlib import Path


RELEASE_NAME = re.compile(r"^\d{8}_\d{6}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_files(release: Path) -> list[Path]:
    manifest = release / "SOURCE_MANIFEST.sha256"
    if not manifest.is_file():
        raise ValueError("missing SOURCE_MANIFEST.sha256")
    files: list[Path] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, separator, relative = line.partition("  ")
        if not separator or len(expected) != 64 or not relative:
            raise ValueError("invalid manifest line")
        target = (release / relative).resolve()
        if release.resolve() not in target.parents or not target.is_file():
            raise ValueError(f"unsafe or missing manifest file: {relative}")
        if sha256(target) != expected:
            raise ValueError(f"manifest mismatch: {relative}")
        files.append(target)
    if len(files) < 100:
        raise ValueError(f"manifest is unexpectedly small: {len(files)}")
    return files


def protected_releases(base: Path, keep: int) -> set[str]:
    releases = sorted(path.name for path in base.iterdir() if path.is_dir() and RELEASE_NAME.fullmatch(path.name))
    protected = set(releases[-keep:])
    current = (base.parent / "current").resolve()
    if current.parent == base.resolve():
        protected.add(current.name)
    state_path = base.parent / "runtime/slots.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for key in ("active_release", "rollback_release"):
            value = state.get(key)
            if isinstance(value, str) and RELEASE_NAME.fullmatch(value):
                protected.add(value)
    return protected


def archive_release(release: Path, archive_dir: Path) -> tuple[Path, str, int]:
    files = manifest_files(release)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{release.name}-source.tar.gz"
    if not archive.exists():
        temporary = archive.with_suffix(archive.suffix + ".tmp")
        with tarfile.open(temporary, "w:gz") as output:
            output.add(release / "SOURCE_MANIFEST.sha256", arcname="SOURCE_MANIFEST.sha256")
            for path in files:
                output.add(path, arcname=path.relative_to(release))
        temporary.replace(archive)
    with tarfile.open(archive, "r:gz") as check:
        members = [member for member in check.getmembers() if member.isfile()]
        if len(members) != len(files) + 1:
            raise ValueError(f"archive member count mismatch: {archive}")
    digest = sha256(archive)
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, digest, len(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("/opt/milana-erp/releases"))
    parser.add_argument("--archive-dir", type=Path, default=Path("/opt/milana-erp/shared/release-archives"))
    parser.add_argument("--keep", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-host", default="")
    args = parser.parse_args()
    base = args.base.resolve()
    if base != Path("/opt/milana-erp/releases"):
        raise SystemExit(f"Refusing unexpected release root: {base}")
    if args.keep < 3:
        raise SystemExit("Retention must keep at least three recent releases")
    hostname = socket.gethostname()
    if args.apply and args.confirm_host != hostname:
        raise SystemExit(f"--apply requires --confirm-host {hostname}")

    protected = protected_releases(base, args.keep)
    releases = sorted(path for path in base.iterdir() if path.is_dir() and RELEASE_NAME.fullmatch(path.name))
    report: list[dict[str, object]] = []
    for release in releases:
        if release.name in protected:
            report.append({"release": release.name, "action": "keep", "reason": "protected"})
            continue
        try:
            files = manifest_files(release)
        except Exception as exc:  # noqa: BLE001 - unsafe releases must be skipped
            report.append({"release": release.name, "action": "skip", "reason": str(exc)})
            continue
        if args.apply:
            archive, digest, count = archive_release(release, args.archive_dir)
            shutil.rmtree(release)
            action = "archived-and-removed"
            evidence = {
                "archive": str(archive),
                "archive_sha256": digest,
                "source_files": count,
            }
        else:
            action = "would-archive-and-remove"
            evidence = {"source_files": len(files)}
        report.append({"release": release.name, "action": action, **evidence})
    print(json.dumps({"host": hostname, "apply": args.apply, "protected": sorted(protected), "releases": report}, indent=2))


if __name__ == "__main__":
    main()
