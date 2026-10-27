from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
EXPECTED_REF = "refs/heads/codex/ismail-finance-pilot-20261025"
EXPECTED_API = "http://127.0.0.1:8107"
EXPECTED_NEXT = "16.3.8"
REQUIRED_ROOT_MANIFESTS = (
    "BUILD_ID",
    "build-manifest.json",
    "images-manifest.json",
    "prerender-manifest.json",
    "react-loadable-manifest.json",
    "required-server-files.json",
    "routes-manifest.json",
)
FORBIDDEN_SUFFIXES = {
    ".dll", ".dylib", ".exe", ".node", ".pyd", ".so", ".wasm"
}
WINDOWS_RESERVED = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
SECRET_NAMES = {
    "credentials", "credentials.json", "id_ed25519", "id_rsa", "secrets",
    "secrets.json", "service-account.json", "token", "token.json"
}
FORBIDDEN_ENDPOINTS = (
    b"https://erp.milanapremium.uz",
    b"http://172.16.10.4:8000",
)


class PackageError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise PackageError(message)


def run_text(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PackageError(f"Command output was not UTF-8: {args[0]}") from exc


def run_bytes(args: list[str], cwd: Path) -> bytes:
    return subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_safe_member(path: str, seen: set[str]) -> None:
    if "\\" in path or ":" in path or path.startswith("/") or path.startswith("//"):
        fail(f"Unsafe archive member path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in path.split("/")):
        fail(f"Unsafe archive member path: {path!r}")
    folded_parts = []
    for part in pure.parts:
        if part.casefold() in {"node_modules", "standalone", "cache", ".cache", "__pycache__"}:
            fail(f"Dependency or cache directory is forbidden: {path!r}")
        if any(char in '<>"|?*' or ord(char) < 32 or ord(char) == 127 for char in part):
            fail(f"Windows-invalid archive member: {path!r}")
        if part.endswith((".", " ")) or WINDOWS_RESERVED.fullmatch(part):
            fail(f"Windows-unsafe archive member: {path!r}")
        folded_parts.append(part.casefold())
    folded = "/".join(folded_parts)
    if folded in seen:
        fail(f"Case-folded archive path collision: {path!r}")
    seen.add(folded)
    basename = pure.name.casefold()
    if basename.startswith(".env") or basename in SECRET_NAMES:
        fail(f"Secret-like basename is forbidden: {path!r}")
    if any(suffix.casefold() in FORBIDDEN_SUFFIXES for suffix in pure.suffixes):
        fail(f"Native or executable file is forbidden: {path!r}")
    if basename.endswith((".pem", ".key", ".p12", ".pfx", ".log")):
        fail(f"Secret or log file is forbidden: {path!r}")


def collect_tree(root: Path, relative_root: str, seen: set[str]) -> list[tuple[str, Path]]:
    if not root.exists():
        fail(f"Required runtime directory is missing: {relative_root}")
    if root.is_symlink() or not root.is_dir():
        fail(f"Runtime root must be a real directory: {relative_root}")
    result: list[tuple[str, Path]] = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        rel = candidate.relative_to(root).as_posix()
        archive_name = f"{relative_root}/{rel}"
        ensure_safe_member(archive_name, seen)
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
            fail(f"Symlink or special file is forbidden: {archive_name}")
        if stat.S_ISDIR(info.st_mode):
            continue
        result.append((archive_name, candidate))
    if not result:
        fail(f"Runtime directory is empty: {relative_root}")
    return result


def collect_files(frontend: Path) -> list[tuple[str, Path]]:
    build = frontend / ".next"
    if build.is_symlink() or not build.is_dir():
        fail("frontend/.next must be a real build directory")
    seen: set[str] = set()
    files: list[tuple[str, Path]] = []
    files += collect_tree(build / "server", ".next/server", seen)
    files += collect_tree(build / "static", ".next/static", seen)

    for name in REQUIRED_ROOT_MANIFESTS:
        path = build / name
        if path.is_symlink() or not path.is_file():
            fail(f"Required Next manifest is missing or unsafe: .next/{name}")
        archive_name = f".next/{name}"
        ensure_safe_member(archive_name, seen)
        files.append((archive_name, path))

    for name in ("next.config.js", "package.json", "package-lock.json"):
        path = frontend / name
        if path.is_symlink() or not path.is_file():
            fail(f"Required frontend runtime file is missing or unsafe: {name}")
        ensure_safe_member(name, seen)
        files.append((name, path))

    public = frontend / "public"
    if not public.is_dir() or public.is_symlink():
        fail("public must be a real directory")
    files += collect_tree(public, "public", seen)
    files = sorted(files, key=lambda item: item[0])
    total = sum(path.stat().st_size for _, path in files)
    if total > MAX_BYTES:
        fail(f"Uncompressed allowlist exceeds 20 MiB: {total} bytes")
    return files


def validate_routes(frontend: Path, build: Path) -> None:
    routes_path = build / "routes-manifest.json"
    try:
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError("Cannot parse .next/routes-manifest.json") from exc
    raw_rewrites = routes.get("rewrites")
    if isinstance(raw_rewrites, list):
        rewrites = raw_rewrites
    elif isinstance(raw_rewrites, dict):
        rewrites = []
        for key in ("beforeFiles", "afterFiles", "fallback"):
            value = raw_rewrites.get(key, [])
            if not isinstance(value, list):
                fail(f"Invalid rewrite group in routes manifest: {key}")
            rewrites.extend(value)
    else:
        fail("Unexpected rewrites shape in routes manifest")

    if len(rewrites) != 3:
        fail("Built route manifest must contain exactly three rewrites")

    expected = {
        "/api/:path*": f"{EXPECTED_API}/api/:path*",
        "/storage/:path*": f"{EXPECTED_API}/storage/:path*",
        "/health": f"{EXPECTED_API}/health",
    }
    found: dict[str, str] = {}
    for route in rewrites:
        if not isinstance(route, dict):
            fail("Invalid rewrite entry")
        source = route.get("source")
        destination = route.get("destination")
        if source in expected:
            if source in found:
                fail(f"Duplicate required rewrite: {source}")
            found[source] = destination
        if isinstance(destination, str) and destination.startswith(("http://", "https://")):
            if not destination.startswith(EXPECTED_API + "/"):
                fail(f"External rewrite destination is forbidden: {source}")
    if found != expected:
        fail("Built rewrite manifest does not contain exactly the three QA loopback routes")

    redirects = routes.get("redirects", [])
    expected_redirects = {
        ("/:path+/", "/:path+", 308, True, True),
        ("/warehouse", "/warehouse-map", 307, False, False),
    }
    actual_redirects = set()
    if not isinstance(redirects, list) or len(redirects) != len(expected_redirects):
        fail("Built route manifest must contain only the reviewed internal redirects")
    for redirect in redirects:
        if not isinstance(redirect, dict):
            fail("Invalid redirect entry")
        destination = redirect.get("destination")
        if isinstance(destination, str) and destination.startswith(("http://", "https://")):
            fail("External redirect destination is forbidden")
        actual_redirects.add((
            redirect.get("source"),
            destination,
            redirect.get("statusCode"),
            redirect.get("internal") is True,
            redirect.get("priority") is True,
        ))
    if actual_redirects != expected_redirects:
        fail("Unexpected redirect in built route manifest")

    required = build / "required-server-files.json"
    try:
        required_data = json.loads(required.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError("Cannot parse required-server-files.json") from exc
    config = required_data.get("config", {})
    if not isinstance(config, dict):
        fail("Invalid Next required-server-files config")
    asset_prefix = config.get("assetPrefix")
    if asset_prefix not in (None, ""):
        fail("External or non-empty Next assetPrefix is forbidden")
    if config.get("output") != "standalone":
        fail("Unexpected Next output mode")
    config_env = config.get("env", {})
    if not isinstance(config_env, dict):
        fail("Invalid Next config env map")
    public_values = [value for key, value in config_env.items() if key.startswith("NEXT_PUBLIC_")]
    if any(value not in ("", None) for value in public_values):
        fail("Built config contains a non-empty public environment value")

    for archive_name, file_path in collect_files(frontend):
        raw = file_path.read_bytes()
        if any(endpoint in raw for endpoint in FORBIDDEN_ENDPOINTS):
            fail(f"Production endpoint string found in QA runtime: {archive_name}")
        if archive_name.startswith(".next/static/") and EXPECTED_API.encode("ascii") in raw:
            fail(f"Loopback API origin leaked into client assets: {archive_name}")


def main() -> int:
    if sys.version_info < (3, 11):
        fail("Python 3.11 or newer is required")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    if event != "push" or ref != EXPECTED_REF:
        fail("QA runtime staging is restricted to the exact authorized push ref")
    if os.environ.get("NODE_ENV") != "production":
        fail("NODE_ENV must be production")
    if os.environ.get("API_URL") != EXPECTED_API:
        fail("API_URL must be the exact QA loopback origin")
    if os.environ.get("NEXT_PUBLIC_API_URL") != "":
        fail("NEXT_PUBLIC_API_URL must be explicitly blank")
    if os.environ.get("NEXT_TELEMETRY_DISABLED") != "1":
        fail("Next telemetry must be disabled")

    script = Path(__file__).resolve()
    frontend = script.parents[1]
    repo = script.parents[2]
    if Path.cwd().resolve() != frontend:
        fail("Run this script with frontend as the working directory")
    runner_temp = Path(os.environ.get("RUNNER_TEMP", "")).resolve()
    if not runner_temp.is_dir():
        fail("RUNNER_TEMP must be an existing directory")
    output = runner_temp / f"finance-qa-runtime-{os.environ.get('GITHUB_SHA', '')}"
    if output.parent != runner_temp or output.exists() or output.is_symlink():
        fail("Output must be a new direct child of RUNNER_TEMP")
    output.mkdir(mode=0o700)

    status = run_text(["git", "status", "--porcelain=v1", "--untracked-files=all", "--", "frontend"], repo)
    if status:
        fail("Frontend checkout is not clean after QA build")
    head = run_text(["git", "rev-parse", "HEAD"], repo)
    tree = run_text(["git", "rev-parse", "HEAD^{tree}"], repo)
    github_sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", github_sha):
        fail("GITHUB_SHA must be a full hexadecimal commit id")
    if head != github_sha:
        fail("GITHUB_SHA does not match the actual checked-out HEAD")

    package_data = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    lock_bytes = (frontend / "package-lock.json").read_bytes()
    git_lock_bytes = run_bytes(["git", "show", "HEAD:frontend/package-lock.json"], repo)
    lock_data = json.loads(lock_bytes)
    next_lock = lock_data.get("packages", {}).get("node_modules/next", {}).get("version")
    next_package = json.loads((frontend / "node_modules/next/package.json").read_text(encoding="utf-8"))
    if next_lock != EXPECTED_NEXT or next_package.get("version") != EXPECTED_NEXT:
        fail("Locked and installed Next versions must both equal the reviewed version")
    node_version = run_text(["node", "--version"], frontend)
    npm_version = run_text(["npm", "--version"], frontend)
    if not node_version.startswith("v20."):
        fail("CI QA artifact must be built by Node 20")

    build = frontend / ".next"
    build_id_path = build / "BUILD_ID"
    if build_id_path.is_symlink() or not build_id_path.is_file():
        fail("Next BUILD_ID is missing or unsafe")
    build_id = build_id_path.read_text(encoding="utf-8").strip()
    if not build_id:
        fail("Next BUILD_ID is empty")
    validate_routes(frontend, build)
    files = collect_files(frontend)

    total = sum(path.stat().st_size for _, path in files)
    if total > MAX_BYTES:
        fail(f"Uncompressed allowlist exceeds 20 MiB: {total} bytes")

    archive_path = output / "runtime.zip"
    manifest_path = output / "manifest.json"
    entries = []
    packaged_total = 0
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in files:
            data = path.read_bytes()
            packaged_total += len(data)
            if packaged_total > MAX_BYTES:
                fail("Runtime files grew beyond the uncompressed cap while packaging")
            archive.writestr(name, data)
            if archive.fp.tell() > 2 * MAX_BYTES:
                fail("Compressed artifact exceeded the bounded temporary-write envelope")
            entries.append({"path": name, "bytes": len(data), "sha256": sha256_bytes(data)})
    if packaged_total != total:
        fail("Runtime files changed while the archive was being produced")
    archive_bytes = archive_path.stat().st_size
    if archive_bytes > MAX_BYTES:
        fail(f"Compressed runtime artifact exceeds 20 MiB: {archive_bytes} bytes")
    manifest: dict[str, Any] = {
        "schema": "finance-qa-runtime-v1",
        "candidate": {
            "git_head": head,
            "git_tree": tree,
            "github_event": event,
            "github_ref": ref,
            "github_sha": github_sha,
            "frontend_clean_after_build": True,
        },
        "package": {
            "name": package_data.get("name"),
            "next_version_locked": next_lock,
            "next_version_installed": next_package.get("version"),
            "package_lock_git_blob_content_sha256": sha256_bytes(git_lock_bytes),
            "package_lock_checkout_sha256": sha256_bytes(lock_bytes),
        },
        "build": {
            "node_version": node_version,
            "npm_version": npm_version,
            "build_id": build_id,
            "node_env": "production",
            "api_url": EXPECTED_API,
            "next_public_api_url": "",
            "telemetry_disabled": True,
        },
        "runtime": {
            "files": entries,
            "file_count": len(entries),
            "uncompressed_bytes": total,
            "max_uncompressed_bytes": MAX_BYTES,
            "archive": "runtime.zip",
            "archive_bytes": archive_bytes,
            "max_archive_bytes": MAX_BYTES,
            "archive_sha256": sha256_file(archive_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": "QA_RUNTIME_STAGED",
        "artifact_dir": str(output),
        "file_count": len(entries),
        "uncompressed_bytes": total,
        "archive_bytes": archive_bytes,
        "archive_sha256": manifest["runtime"]["archive_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackageError as exc:
        print(f"QA runtime staging refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
