"""Isolated regression and mutation checks for the QA artifact route allowlist."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("stage_qa_runtime.py")
spec = importlib.util.spec_from_file_location("stage_qa_runtime_proposal", SCRIPT)
producer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(producer)


class AppRouteManifestTests(unittest.TestCase):
    def setUp(self):
        temp_root = SCRIPT.parent / "test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.build = Path(self.temp.name) / ".next"
        server = self.build / "server"
        (server / "app" / "(app)").mkdir(parents=True)
        (server / "app" / "login").mkdir(parents=True)
        (server / "app" / "(app)" / "customers" / "[id]").mkdir(parents=True)
        (server / "app" / "(app)" / "page.js").write_text("root bundle", encoding="utf-8")
        (server / "app" / "login" / "page.js").write_text("login bundle", encoding="utf-8")
        (server / "app" / "(app)" / "customers" / "[id]" / "page.js").write_text("customer bundle", encoding="utf-8")
        self.route_map = {"/(app)/page": "/", "/login/page": "/login", "/(app)/customers/[id]/page": "/customers/[id]"}
        self.app_paths = {
            "/(app)/page": "app/(app)/page.js",
            "/login/page": "app/login/page.js",
            "/(app)/customers/[id]/page": "app/(app)/customers/[id]/page.js",
        }
        self.write_manifests()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifests(self, route_map=None, app_paths=None, raw_route_map=None):
        self.build.mkdir(parents=True, exist_ok=True)
        route_path = self.build / "app-path-routes-manifest.json"
        if raw_route_map is not None:
            route_path.write_text(raw_route_map, encoding="utf-8")
        elif route_map is not None or not route_path.exists():
            route_path.write_text(json.dumps(route_map if route_map is not None else self.route_map), encoding="utf-8")
        paths_path = self.build / "server" / "app-paths-manifest.json"
        paths_path.parent.mkdir(parents=True, exist_ok=True)
        paths_path.write_text(json.dumps(app_paths if app_paths is not None else self.app_paths), encoding="utf-8")

    def assert_refused(self):
        with self.assertRaises(producer.PackageError):
            producer.validate_app_routes(self.build)

    def test_realistic_root_and_login_mapping_resolves_to_compiled_files(self):
        producer.validate_app_routes(self.build)
        self.assertIn("app-path-routes-manifest.json", producer.REQUIRED_ROOT_MANIFESTS)

    def test_missing_root_manifest_is_rejected(self):
        (self.build / "app-path-routes-manifest.json").unlink()
        self.assert_refused()

    def test_wrong_customer_route_is_rejected(self):
        self.write_manifests(route_map={**self.route_map, "/(app)/customers/[id]/page": "/wrong"})
        self.assert_refused()

    def test_external_control_or_traversal_pathname_is_rejected(self):
        extra = self.build / "server" / "app" / "extra" / "page.js"
        extra.parent.mkdir(parents=True)
        extra.write_text("extra bundle", encoding="utf-8")
        for value in ("//example.test", "/bad\x00path", "/../outside", "/bad:route"):
            with self.subTest(value=value):
                self.write_manifests(route_map={**self.route_map, "/extra/page": value},
                                     app_paths={**self.app_paths, "/extra/page": "app/extra/page.js"})
                self.assert_refused()

    def test_empty_route_map_is_rejected(self):
        self.write_manifests(route_map={})
        self.assert_refused()

    def test_malformed_json_is_rejected(self):
        self.write_manifests(raw_route_map="{")
        self.assert_refused()

    def test_non_object_route_map_is_rejected(self):
        self.write_manifests(raw_route_map="[]")
        self.assert_refused()

    def test_key_set_must_match_server_manifest(self):
        self.write_manifests(route_map={"/(app)/page": "/"})
        self.assert_refused()

    def test_root_route_is_required(self):
        self.write_manifests(route_map={key: value for key, value in self.route_map.items() if key != "/(app)/page"},
                             app_paths={key: value for key, value in self.app_paths.items() if key != "/(app)/page"})
        self.assert_refused()

    def test_login_route_is_required_and_pathname_must_match(self):
        self.write_manifests(route_map={**self.route_map, "/login/page": "/sign-in"})
        self.assert_refused()

    def test_missing_compiled_route_is_rejected(self):
        (self.build / "server" / "app" / "login" / "page.js").unlink()
        self.assert_refused()

    def test_compiled_path_traversal_is_rejected(self):
        self.write_manifests(app_paths={**self.app_paths, "/(app)/page": "app/../outside.js"})
        self.assert_refused()

    def test_compiled_path_outside_app_tree_is_rejected(self):
        self.write_manifests(app_paths={**self.app_paths, "/(app)/page": "pages/index.js"})
        self.assert_refused()

    def test_invalid_pathname_type_is_rejected(self):
        self.write_manifests(route_map={**self.route_map, "/login/page": None})
        self.assert_refused()

    def test_required_server_files_all_have_package_members(self):
        declaration = {"files": [".next/app-path-routes-manifest.json", ".next/package.json"]}
        members = [
            (".next/app-path-routes-manifest.json", Path("route-map")),
            (".next/package.json", Path("package-manifest")),
        ]
        producer.validate_required_file_members(declaration, members)

    def test_missing_declared_package_file_is_rejected(self):
        declaration = {"files": [".next/package.json"]}
        with self.assertRaises(producer.PackageError):
            producer.validate_required_file_members(declaration, [])

    def test_unsafe_or_duplicate_required_file_is_rejected(self):
        members = [(".next/package.json", Path("package-manifest"))]
        for declaration in (
            {"files": [".next/../outside"]},
            {"files": [".next/package.json", ".next/package.json"]},
        ):
            with self.subTest(declaration=declaration), self.assertRaises(producer.PackageError):
                producer.validate_required_file_members(declaration, members)


class PushRefAllowlistTests(unittest.TestCase):
    def test_only_the_three_approved_push_refs_are_accepted(self):
        self.assertEqual(producer.EXPECTED_REFS, frozenset((
            "refs/heads/codex/ismail-finance-pilot-20261025",
            "refs/heads/codex/ismail-brand-feedback-20261028",
            "refs/heads/codex/ismail-combined-review-20261028",
        )))
        for ref in producer.EXPECTED_REFS:
            with self.subTest(ref=ref):
                self.assertTrue(producer.is_authorized_push_ref("push", ref))
        self.assertFalse(producer.is_authorized_push_ref("push", "refs/heads/codex/unapproved"))
        self.assertFalse(producer.is_authorized_push_ref("pull_request", next(iter(producer.EXPECTED_REFS))))


if __name__ == "__main__":
    unittest.main()
