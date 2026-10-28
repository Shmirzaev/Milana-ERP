from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

from stage_qa_runtime import EXPECTED_API, EXPECTED_NEXT, EXPECTED_REF, MAX_BYTES, PackageError, ensure_safe_member

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_RUNTIME_FILES = 2000
STARTUP_SECONDS = 35


class SmokeError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> None:
    raise SmokeError(message)


def validate_archive(manifest: dict[str, Any], archive_path: Path) -> list[tuple[str, bytes]]:
    if manifest.get("schema") != "finance-qa-runtime-v1":
        fail("Unexpected QA runtime manifest schema")
    candidate = manifest.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("github_event") != "push" or candidate.get("github_ref") != EXPECTED_REF:
        fail("Artifact is not bound to the authorized QA push ref")
    if candidate.get("git_head") != candidate.get("github_sha") or not candidate.get("frontend_clean_after_build"):
        fail("QA artifact source identity is inconsistent")
    build = manifest.get("build")
    if (not isinstance(build, dict) or build.get("node_env") != "production"
            or build.get("api_url") != EXPECTED_API or build.get("next_public_api_url") != ""
            or build.get("telemetry_disabled") is not True):
        fail("QA artifact build environment does not match the loopback-only contract")
    package = manifest.get("package")
    if (not isinstance(package, dict) or package.get("next_version_locked") != EXPECTED_NEXT
            or package.get("next_version_installed") != EXPECTED_NEXT):
        fail("QA artifact Next version is not the reviewed version")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("archive") != "runtime.zip":
        fail("Invalid runtime archive declaration")
    archive_size = archive_path.stat().st_size
    if archive_size > MAX_BYTES:
        fail("Runtime ZIP exceeds the 20 MiB compressed bound")
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if (runtime.get("archive_bytes") != archive_size
            or runtime.get("max_archive_bytes") != MAX_BYTES
            or runtime.get("archive_sha256") != archive_sha):
        fail("Runtime ZIP size or digest does not match its manifest")

    entries = runtime.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_RUNTIME_FILES:
        fail("Runtime manifest file allowlist is empty or exceeds 2,000 entries")
    expected: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    uncompressed = 0
    for entry in entries:
        if not isinstance(entry, dict):
            fail("Malformed runtime file entry")
        name, size, digest = entry.get("path"), entry.get("bytes"), entry.get("sha256")
        if not isinstance(name, str) or not isinstance(size, int) or size < 0:
            fail("Malformed runtime member identity")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            fail("Malformed runtime member hash")
        try:
            ensure_safe_member(name, folded)
        except PackageError as exc:
            raise SmokeError(f"Unsafe manifest member: {name!r}") from exc
        expected[name] = (size, digest)
        uncompressed += size
        if uncompressed > MAX_BYTES:
            fail("Manifest uncompressed runtime exceeds 20 MiB")
    if runtime.get("file_count") != len(expected) or runtime.get("uncompressed_bytes") != uncompressed:
        fail("Runtime manifest file count or byte total is inconsistent")
    if runtime.get("max_uncompressed_bytes") != MAX_BYTES:
        fail("Unexpected runtime uncompressed size bound")

    verified: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_RUNTIME_FILES:
                fail("Runtime ZIP contains more than 2,000 members")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != set(expected):
                fail("ZIP members do not exactly match the manifest allowlist")
            actual_casefold: set[str] = set()
            total = 0
            for info in infos:
                if info.is_dir():
                    fail("Directory entries are not allowed in the runtime ZIP")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG):
                    fail("Links or special files are forbidden in the runtime ZIP")
                try:
                    ensure_safe_member(info.filename, actual_casefold)
                except PackageError as exc:
                    raise SmokeError(f"Unsafe ZIP member: {info.filename!r}") from exc
                size, digest = expected[info.filename]
                if info.file_size != size:
                    fail(f"ZIP member declared size differs from manifest: {info.filename}")
                content = bytearray()
                with archive.open(info, "r") as member:
                    while len(content) <= size:
                        chunk = member.read(min(65536, size + 1 - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > size:
                            fail(f"ZIP member expands beyond its declared bound: {info.filename}")
                data = bytes(content)
                if len(data) != size or sha256_bytes(data) != digest:
                    fail(f"ZIP member failed size/hash verification: {info.filename}")
                total += len(data)
                if total > MAX_BYTES:
                    fail("ZIP expands beyond the 20 MiB runtime bound")
                verified.append((info.filename, data))
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise SmokeError("Cannot safely read the runtime ZIP") from exc
    if total != uncompressed:
        fail("ZIP expanded byte total differs from the manifest")
    names = {name for name, _ in verified}
    required = {
        ".next/app-path-routes-manifest.json",
        ".next/package.json",
        ".next/required-server-files.json",
        ".next/server/app-paths-manifest.json",
    }
    if not required.issubset(names):
        fail("ZIP omits required Next root or server manifests")
    by_name = dict(verified)
    try:
        route_map = json.loads(by_name[".next/app-path-routes-manifest.json"])
        app_paths = json.loads(by_name[".next/server/app-paths-manifest.json"])
        server_required = json.loads(by_name[".next/required-server-files.json"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SmokeError("Packaged App Router manifests are malformed") from exc
    if not isinstance(route_map, dict) or not route_map or not isinstance(app_paths, dict) or not app_paths:
        fail("Packaged App Router manifests must be non-empty objects")
    if set(route_map) != set(app_paths):
        fail("Packaged route map and server app paths disagree")
    for key, path in app_paths.items():
        if (not isinstance(key, str) or not isinstance(path, str) or not path.startswith("app/")
                or "\\" in path or ":" in path or PurePosixPath(path).is_absolute()
                or any(part in ("", ".", "..") for part in path.split("/")) or not path.endswith(".js")):
            fail("Unsafe compiled app route path in packaged manifest")
        if ".next/server/" + path not in names:
            fail(f"Compiled app route is absent from ZIP: {path}")
        pathname = route_map[key]
        if not isinstance(pathname, str) or not pathname.startswith("/") or "\\" in pathname or "?" in pathname or "#" in pathname:
            fail("Unsafe pathname in packaged route map")
    if route_map.get("/(app)/page") != "/" or route_map.get("/login/page") != "/login":
        fail("Packaged App Router map does not resolve `/` and `/login`")
    required_files = server_required.get("files") if isinstance(server_required, dict) else None
    if not isinstance(required_files, list) or not required_files:
        fail("Packaged required-server-files manifest has no file list")
    normalized = set()
    for name in required_files:
        if not isinstance(name, str):
            fail("Malformed Next required-server-files entry")
        path = name.replace("\\", "/")
        pure = PurePosixPath(path)
        if not path.startswith(".next/") or pure.is_absolute() or ":" in path or any(part in ("", ".", "..") for part in path.split("/")):
            fail("Unsafe Next required-server-files path")
        if path in normalized or path not in names:
            fail("Duplicate or missing Next-required ZIP member")
        normalized.add(path)
    return verified


def extract_verified(files: list[tuple[str, bytes]], destination: Path) -> None:
    destination.mkdir(mode=0o700)
    root = destination.resolve(strict=True)
    for name, data in files:
        target = destination.joinpath(*PurePosixPath(name).parts)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        current = parent
        while current != destination:
            if current.is_symlink() or not current.is_dir():
                fail("Unsafe extraction parent")
            current = current.parent
        if not target.resolve(strict=False).is_relative_to(root):
            fail("Archive member escapes owned extraction directory")
        with target.open("xb") as stream:
            stream.write(data)


class _PageMarkers(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.login_password_input = False
        self.root_loading_shell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("id") == "login-password" and values.get("name") == "password" and values.get("type", "").casefold() == "password":
            self.login_password_input = True
        if tag == "div":
            classes = set((values.get("class") or "").split())
            auth_gate_shell = {"p-6", "text-slate-500"}.issubset(classes)
            suspense_shell = "p-6" in classes and values.get("aria-busy", "").casefold() == "true"
            if auth_gate_shell or suspense_shell:
                self.root_loading_shell = True


def assert_page_response(path: str, status: int, content_type: str, body: bytes) -> None:
    if "text/html" not in content_type.casefold():
        fail(f"{path} did not return HTML")
    markers = _PageMarkers()
    markers.feed(body.decode("utf-8", errors="replace"))
    if status == 404:
        fail(f"{path} returned HTTP 404")
    if path == "/login":
        if status != 200 or not markers.login_password_input:
            fail("/login did not render the expected password form")
    elif path == "/":
        # AuthGate's SSR loading div or AppLayout's Suspense fallback must render.
        if status != 200 or not markers.root_loading_shell:
            fail("/ did not render the expected AuthGate/Suspense shell")
    else:
        fail("Smoke requested an unreviewed route")


def fetch_page(port: int, path: str) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path, headers={"Accept": "text/html"})
        response = connection.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader("Location", "")
            fail(f"{path} unexpectedly redirected to {location!r}")
        body = response.read(MAX_PAGE_BYTES + 1)
        if len(body) > MAX_PAGE_BYTES:
            fail(f"{path} response exceeds the 2 MiB smoke bound")
        assert_page_response(path, response.status, response.getheader("Content-Type", ""), body)
    finally:
        connection.close()


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    if not sys.platform.startswith("linux"):
        fail("QA artifact smoke is restricted to the Ubuntu Linux CI runner")
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != EXPECTED_REF:
        fail("QA artifact smoke is restricted to the authorized push ref")
    sha = os.environ.get("GITHUB_SHA", "")
    if len(sha) not in (40, 64) or any(char not in "0123456789abcdef" for char in sha):
        fail("GITHUB_SHA must be a full lowercase commit id")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "")
    if not runner_temp_value:
        fail("RUNNER_TEMP must be set")
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    artifact_dir = runner_temp / f"finance-qa-runtime-{sha}"
    if artifact_dir.parent != runner_temp or artifact_dir.is_symlink() or not artifact_dir.is_dir():
        fail("Expected staged artifact directory is absent or unsafe")
    manifest_path = artifact_dir / "manifest.json"
    archive_path = artifact_dir / "runtime.zip"
    if manifest_path.is_symlink() or archive_path.is_symlink():
        fail("Staged artifact files must not be symlinks")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        fail("Artifact manifest exceeds the 8 MiB limit")
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    if not isinstance(manifest, dict):
        fail("Artifact manifest must be a JSON object")
    candidate = manifest.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("github_sha") != sha:
        fail("Staged QA manifest is for a different source commit")
    files = validate_archive(manifest, archive_path)

    frontend = Path(__file__).resolve().parents[1]
    node_modules = frontend / "node_modules"
    if node_modules.is_symlink() or not node_modules.is_dir():
        fail("Existing frontend node_modules must be a real directory")
    next_package = json.loads((node_modules / "next" / "package.json").read_text(encoding="utf-8"))
    if next_package.get("version") != EXPECTED_NEXT:
        fail("Existing CI Next installation does not match the reviewed version")
    next_cli = node_modules / "next" / "dist" / "bin" / "next"
    if next_cli.is_symlink() or not next_cli.is_file():
        fail("Existing Next CLI is missing or unsafe")
    node = shutil.which("node")
    if not node:
        fail("Node executable is unavailable")

    owned = Path(tempfile.mkdtemp(prefix="qa-artifact-smoke-", dir=runner_temp))
    app_root = owned / "app"
    child: subprocess.Popen[bytes] | None = None
    try:
        if owned.parent != runner_temp or owned.is_symlink() or not owned.is_dir():
            fail("Could not establish a fresh owned smoke directory")
        extract_verified(files, app_root)
        os.symlink(node_modules.resolve(strict=True), app_root / "node_modules", target_is_directory=True)
        port = reserve_loopback_port()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "NODE_ENV": "production",
            "API_URL": EXPECTED_API,
            "NEXT_PUBLIC_API_URL": "",
            "NEXT_TELEMETRY_DISABLED": "1",
            "HOSTNAME": "127.0.0.1",
            "PORT": str(port),
            "TMPDIR": str(owned),
        }
        child = subprocess.Popen(
            [node, str(next_cli), "start", "--hostname", "127.0.0.1", "--port", str(port)],
            cwd=app_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        deadline = time.monotonic() + STARTUP_SECONDS
        last_error = "server did not become ready"
        while time.monotonic() < deadline:
            if child.poll() is not None:
                fail(f"Owned Next process exited during startup ({child.returncode})")
            try:
                fetch_page(port, "/login")
                fetch_page(port, "/")
                print("QA artifact route smoke passed: /login password form; / home shell")
                return 0
            except (OSError, http.client.HTTPException) as exc:
                last_error = str(exc)
                time.sleep(0.25)
        fail(f"QA artifact route smoke timed out: {last_error}")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        if owned.parent == runner_temp and owned.is_dir() and not owned.is_symlink():
            shutil.rmtree(owned)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeError, PackageError, OSError, json.JSONDecodeError) as exc:
        print(f"QA artifact smoke refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
