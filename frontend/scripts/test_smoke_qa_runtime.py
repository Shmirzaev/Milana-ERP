"""Pure synthetic security and response checks for the QA ZIP smoke helper."""
import hashlib
import importlib.util
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).parent
for directory in (str(SCRIPTS),):
    import sys
    if directory not in sys.path:
        sys.path.insert(0, directory)

spec = importlib.util.spec_from_file_location("qa_smoke_proposal", SCRIPTS / "smoke_qa_runtime.py")
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(smoke)

ROUTES = {
    ".next/app-path-routes-manifest.json": json.dumps({"/(app)/page": "/", "/login/page": "/login"}).encode(),
    ".next/server/app-paths-manifest.json": json.dumps({"/(app)/page": "app/(app)/page.js", "/login/page": "app/login/page.js"}).encode(),
    ".next/required-server-files.json": json.dumps({"files": [
        ".next/app-path-routes-manifest.json", ".next/package.json",
        ".next/server/app-paths-manifest.json", ".next/server/app/(app)/page.js",
        ".next/server/app/login/page.js",
    ]}).encode(),
    ".next/package.json": b'{"type":"commonjs"}',
    ".next/server/app/(app)/page.js": b"root compiled app route",
    ".next/server/app/login/page.js": b"login compiled app route",
}


class SmokeRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp_root = SCRIPTS / "test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.archive = self.root / "runtime.zip"
        self.files = dict(ROUTES)
        self.current_ref = sorted(smoke.EXPECTED_REFS)[0]

    def tearDown(self):
        self.temp.cleanup()

    def build_manifest(self, member_overrides=None, zip_extra=None, symlink_member=None):
        entries = []
        for name, data in self.files.items():
            entries.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if member_overrides:
            for entry in entries:
                entry.update(member_overrides.get(entry["path"], {}))
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.files.items():
                info = zipfile.ZipInfo(name)
                if symlink_member == name:
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, data)
            for name, data in (zip_extra or {}).items():
                archive.writestr(name, data)
        raw = self.archive.read_bytes()
        return {
            "schema": "finance-qa-runtime-v1",
            "candidate": {"github_event": "push", "github_ref": self.current_ref,
                          "git_head": "a" * 40, "github_sha": "a" * 40,
                          "frontend_clean_after_build": True},
            "build": {"node_env": "production", "api_url": smoke.EXPECTED_API,
                      "next_public_api_url": "", "telemetry_disabled": True},
            "package": {"next_version_locked": smoke.EXPECTED_NEXT,
                        "next_version_installed": smoke.EXPECTED_NEXT},
            "runtime": {"archive": "runtime.zip", "archive_bytes": len(raw),
                        "max_archive_bytes": smoke.MAX_BYTES,
                        "archive_sha256": hashlib.sha256(raw).hexdigest(),
                        "files": entries, "file_count": len(entries),
                        "uncompressed_bytes": sum(e["bytes"] for e in entries),
                        "max_uncompressed_bytes": smoke.MAX_BYTES},
        }

    def test_exact_hashed_allowlist_and_real_routes_are_accepted(self):
        files = smoke.validate_archive(self.build_manifest(), self.archive, expected_ref=self.current_ref)
        self.assertEqual({name for name, _ in files}, set(self.files))

    def test_each_allowlisted_manifest_ref_must_match_current_job_ref(self):
        refs = sorted(smoke.EXPECTED_REFS)
        self.assertEqual(set(refs), {
            "refs/heads/codex/ismail-finance-pilot-20261025",
            "refs/heads/codex/ismail-brand-feedback-20261028",
            "refs/heads/codex/ismail-combined-review-20261028",
            "refs/heads/codex/refactor-combined-next-20261030",
        })
        for manifest_ref in refs:
            with self.subTest(manifest_ref=manifest_ref):
                manifest = self.build_manifest()
                manifest["candidate"]["github_ref"] = manifest_ref
                smoke.validate_archive(manifest, self.archive, expected_ref=manifest_ref)
                other_allowed_ref = next(ref for ref in refs if ref != manifest_ref)
                # Same manifest SHA, but a different authorized job ref must refuse it.
                with self.assertRaises(smoke.SmokeError):
                    smoke.validate_archive(manifest, self.archive, expected_ref=other_allowed_ref)

    def test_unapproved_manifest_ref_is_rejected(self):
        manifest = self.build_manifest()
        manifest["candidate"]["github_ref"] = "refs/heads/codex/unapproved"
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_archive_digest_mismatch_is_rejected(self):
        manifest = self.build_manifest()
        manifest["runtime"]["archive_sha256"] = "0" * 64
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_member_size_or_hash_mismatch_is_rejected(self):
        manifest = self.build_manifest({".next/package.json": {"sha256": "0" * 64}})
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_decompressed_member_cannot_exceed_manifest_size(self):
        self.files[".next/package.json"] = b"x" * 12000
        manifest = self.build_manifest({".next/package.json": {"bytes": 1}})
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_traversal_member_is_rejected(self):
        self.files["../escape"] = b"no"
        with self.assertRaises((smoke.SmokeError, smoke.PackageError)):
            smoke.validate_archive(self.build_manifest(), self.archive, expected_ref=self.current_ref)

    def test_unlisted_extra_zip_member_is_rejected(self):
        manifest = self.build_manifest(zip_extra={"extra.txt": b"unexpected"})
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_symlink_zip_member_is_rejected(self):
        manifest = self.build_manifest(symlink_member=".next/package.json")
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(manifest, self.archive, expected_ref=self.current_ref)

    def test_malformed_app_route_manifest_is_rejected(self):
        self.files[".next/app-path-routes-manifest.json"] = b"{"
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(self.build_manifest(), self.archive, expected_ref=self.current_ref)

    def test_missing_app_route_map_is_rejected(self):
        del self.files[".next/app-path-routes-manifest.json"]
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(self.build_manifest(), self.archive, expected_ref=self.current_ref)

    def test_login_route_must_exist_in_route_map(self):
        self.files[".next/app-path-routes-manifest.json"] = json.dumps({"/(app)/page": "/"}).encode()
        self.files[".next/server/app-paths-manifest.json"] = json.dumps({"/(app)/page": "app/(app)/page.js"}).encode()
        required = json.loads(self.files[".next/required-server-files.json"])
        required["files"].remove(".next/server/app/login/page.js")
        self.files[".next/required-server-files.json"] = json.dumps(required).encode()
        self.files.pop(".next/server/app/login/page.js")
        with self.assertRaises(smoke.SmokeError):
            smoke.validate_archive(self.build_manifest(), self.archive, expected_ref=self.current_ref)

    def test_login_404_or_not_found_html_is_rejected(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.assert_page_response("/login", 404, "text/html", b"This page could not be found")

    def test_login_requires_password_form_markers_but_allows_embedded_not_found_fallback(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.assert_page_response("/login", 200, "text/html", b"<html>generic page</html>")
        smoke.assert_page_response("/login", 200, "text/html",
                                   b'<html><input id="login-password" name="password" type="password">'
                                   b'<script>This page could not be found</script></html>')

    def test_home_requires_actual_auth_gate_or_suspense_markup(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.assert_page_response("/", 200, "text/html", b"<html><div role=\"status\">unreached HomePage</div></html>")
        smoke.assert_page_response("/", 200, "text/html",
                                   b'<html><div class="p-6 text-slate-500">Loading</div></html>')
        smoke.assert_page_response("/", 200, "text/html",
                                   b'<html><div aria-busy="true" class="p-6"></div></html>')

    def test_external_or_unreviewed_redirect_cannot_count_as_success(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.assert_page_response("/login", 302, "text/html", b"<html></html>")


if __name__ == "__main__":
    unittest.main()
