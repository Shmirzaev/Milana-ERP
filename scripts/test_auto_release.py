"""Deployment fault challenges on owned files and simulated hosts; never production."""
from __future__ import annotations

import contextlib
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import auto_release_host as host
import auto_release_worker as worker
from release_manifest import fingerprint, identity, validate
from release_ci_identity import select


def plan():
    return {"version": 1, "repository": "Shmirzaev/Milana-ERP", "release": "20261117_120000",
            "commit": "a" * 40, "tree": "b" * 40, "run_id": 123,
            "archive_sha256": "c" * 64, "source_manifest_sha256": "d" * 64,
            "schema_fingerprint": "e" * 64,
            "base": {"release": "20261116_130518", "source_manifest_sha256": "f" * 64,
                     "git_baseline_commit": "1" * 40, "database_revision": "0157_test"},
            "images": {role: f"ghcr.io/shmirzaev/milana-erp-{role}@sha256:" + "2" * 64
                       for role in ("backend", "frontend")}}


def before(role="backend"):
    p = plan()
    return {"role": role, "release": p["base"]["release"], "slot": "blue", "container": "old-" + role,
            "source_manifest_sha256": p["base"]["source_manifest_sha256"],
            "schema_fingerprint": p["schema_fingerprint"]}


class ManifestTests(unittest.TestCase):
    def test_pinned_plan_and_every_identity_field(self):
        p = plan()
        self.assertEqual(validate(p), p)
        for field in ("release", "commit", "tree", "archive_sha256", "source_manifest_sha256", "schema_fingerprint"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate({**p, field: "../untrusted"})

    def test_mutable_image_tags_and_other_registry_are_refused(self):
        for image in ("backend:latest", "ghcr.io/attacker/backend@sha256:" + "2" * 64,
                      "ghcr.io/shmirzaev/milana-erp-backend:20261117_120000"):
            with self.subTest(image=image), self.assertRaises(ValueError):
                validate({**plan(), "images": {**plan()["images"], "backend": image}})

    def test_migration_fingerprint_changes_on_edit_add_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "backend/alembic/versions"
            migrations.mkdir(parents=True)
            a = migrations / "a.py"
            a.write_text("a")
            first = fingerprint(root)
            a.write_text("b")
            self.assertNotEqual(first, fingerprint(root))
            second = fingerprint(root)
            (migrations / "b.py").write_text("c")
            self.assertNotEqual(second, fingerprint(root))
            a.unlink()
            self.assertNotEqual(second, fingerprint(root))

    def test_ci_is_opt_in_for_same_repository_worktree_pushes(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/codex/task", "AUTO_RELEASE_BUILDS": "true",
               "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        self.assertEqual(select(env, plan()["base"])["enabled"], "true")
        for changes in ({"AUTO_RELEASE_BUILDS": "false"}, {"GITHUB_EVENT_NAME": "pull_request"},
                        {"GITHUB_REF": "refs/heads/clone_main"}, {"GITHUB_EVENT_NAME": "schedule"}):
            self.assertEqual(select({**env, **changes}, plan()["base"]), {"enabled": "false"})

    def test_manual_inputs_cannot_inject_shell_or_output_lines(self):
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/clone_main",
               "INPUT_RELEASE": "20261117_120000\nenabled=true", "INPUT_BASE_RELEASE": "20261116_130518",
               "INPUT_BASE_MANIFEST": "f" * 64}
        with self.assertRaises(ValueError):
            select(env, plan()["base"])

    def test_parallel_runs_and_attempts_have_distinct_valid_ids(self):
        env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/codex/task", "AUTO_RELEASE_BUILDS": "true",
               "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        first = select(env, plan()["base"])["release"]
        second = select({**env, "GITHUB_RUN_ID": "124"}, plan()["base"])["release"]
        retry = select({**env, "GITHUB_RUN_ATTEMPT": "2"}, plan()["base"])["release"]
        self.assertEqual(len({first, second, retry}), 3)
        from release_retention import RELEASE_NAME
        for release in (first, second, retry):
            validate({**plan(), "release": release})
            self.assertTrue(RELEASE_NAME.fullmatch(release))

    def test_service_ssh_uses_explicit_pinned_hosts_outside_hidden_home(self):
        config = json.loads((ROOT / "deploy/auto-release-worker.example.json").read_text())
        args = worker.Remote(config).ssh("backend")
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("UserKnownHostsFile=" + config["known_hosts"], args)
        self.assertTrue(config["known_hosts"].startswith("/var/lib/"))
        service = (ROOT / "deploy/auto-release-worker.service").read_text()
        self.assertIn("ProtectHome=true", service)
        self.assertIn("RestartPreventExitStatus=2", service)


class GitHubTrustTests(unittest.TestCase):
    def test_redirected_artifact_download_does_not_forward_token(self):
        data = b"artifact bytes"
        artifact = {"id": 42, "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        opener = Mock()
        opener.open.side_effect = [HTTPError("https://api.github.com", 302, "redirect",
                                            {"Location": "https://owned.blob.core.windows.net/file?signature=x"}, None),
                                   io.BytesIO(data)]
        with patch.object(worker.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(worker.GitHub("TOP_SECRET").download(artifact), data)
        first, redirected = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(first.get_header("Authorization"), "Bearer TOP_SECRET")
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_unexpected_redirect_or_wrong_digest_is_refused(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://api.github.com", 302, "redirect",
                                           {"Location": "https://attacker.invalid/"}, None)
        with patch.object(worker.urllib.request, "build_opener", return_value=opener), self.assertRaises(ValueError):
            worker.GitHub("secret").download({"id": 42, "digest": "sha256:" + "0" * 64})
        self.assertEqual(opener.open.call_count, 1)

    def test_changed_or_missing_policy_cannot_forge_green_evidence(self):
        body = b"reviewed policy"
        policies = {path: hashlib.sha256(body).hexdigest() for path in worker.CI_POLICY_PATHS}
        github = worker.GitHub("secret", policies)
        github.api = Mock(return_value={"encoding": "base64", "content": base64.b64encode(body).decode()})
        github.verify_recipe("a" * 40)
        github.api.return_value["content"] = base64.b64encode(b"replace tests with echo success").decode()
        with self.assertRaises(ValueError):
            github.verify_recipe("a" * 40)
        with self.assertRaises(ValueError):
            worker.GitHub("secret").verify_recipe("a" * 40)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, entries):
        path = self.root / "source.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, content, kind in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.size = len(content) if kind == tarfile.REGTYPE else 0
                entry.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                archive.addfile(entry, io.BytesIO(content))
        return path

    def extract(self, entries):
        archive = self.archive(entries)
        p = plan()
        p["archive_sha256"] = host.sha(archive)
        manifest = next((content for name, content, kind in entries if name == "SOURCE_MANIFEST.sha256"), b"")
        p["source_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        host.extract_archive(archive, self.root / "release", p)

    def test_regular_source_round_trip(self):
        data = b"source bytes\n"
        manifest = f"{hashlib.sha256(data).hexdigest()}  backend/app/main.py\n".encode()
        self.extract([("backend/app/main.py", data, tarfile.REGTYPE),
                      ("SOURCE_MANIFEST.sha256", manifest, tarfile.REGTYPE)])
        self.assertEqual((self.root / "release/backend/app/main.py").read_bytes(), data)

    def test_traversal_symlink_duplicate_secret_and_noncanonical_paths(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("/etc/passwd", tarfile.REGTYPE),
                           ("backend/link", tarfile.SYMTYPE), ("backend/.env", tarfile.REGTYPE),
                           ("backend/./file", tarfile.REGTYPE), ("backend\\file", tarfile.REGTYPE)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([(name, b"x", kind)])
        with self.assertRaises(ValueError):
            self.extract([("backend/a", b"x", tarfile.REGTYPE)] * 2)
        self.assertFalse((self.root / "outside").exists())

    def test_unmanifested_extra_and_wrong_digest_are_refused(self):
        with self.assertRaises(ValueError):
            self.extract([("backend/a", b"x", tarfile.REGTYPE), ("SOURCE_MANIFEST.sha256", b"", tarfile.REGTYPE)])

    def test_zip_bound_to_exact_run_source_and_digest(self):
        p = plan()
        source = b"source"
        p["archive_sha256"] = hashlib.sha256(source).hexdigest()
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("deployment.json", json.dumps(p))
            archive.writestr(f"milana-erp-{p['release']}.tar.gz", source)
            archive.writestr(f"milana-erp-{p['release']}.tar.gz.json", "{}")
        run = {"id": p["run_id"], "head_sha": p["commit"]}
        self.assertEqual(worker.read_bundle(data.getvalue(), run), (p, source))
        with self.assertRaises(ValueError):
            worker.read_bundle(data.getvalue(), {**run, "head_sha": "3" * 40})


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name, value in (("BASE", self.root), ("STATE", self.root / "runtime/auto-release")):
            patcher = patch.object(host, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.h = object.__new__(host.Host)
        self.h.role = "backend"
        self.h.config = {"max_ready_seconds": 3600}
        self.h.ctl = SimpleNamespace(read_state=Mock(return_value={"active_release": plan()["base"]["release"]}),
                                    container_name=lambda role, slot: role + "-" + slot,
                                    activate=Mock(), wait_for_health=Mock())
        self.h.snapshot = Mock(return_value=before())

    def journal(self, phase="ready"):
        p = plan()
        value = {"identity": identity(p), "phase": phase, "before": before(), "candidate": "new",
                 "slot": "green", "ready_at": worker.time.time(), "plan": p}
        host.atomic(self.h.record(p), value)
        host.atomic(host.STATE / "reservation.json", {"release": p["release"], "identity": identity(p)})
        return value

    def test_drift_or_migration_change_refused(self):
        for key in ("release", "source_manifest_sha256", "schema_fingerprint"):
            self.h.snapshot.return_value = {**before(), key: "changed"}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.h.baseline(plan())

    def test_recovery_before_host_journal_exists_is_verified_noop(self):
        self.assertEqual(self.h.recover(plan()), before())
        self.h.ctl.activate.assert_not_called()
        self.h.snapshot.return_value = {**before(), "release": "another"}
        with self.assertRaises(ValueError):
            self.h.recover(plan())

    def test_unchanged_recovery_preserves_running_routing(self):
        self.journal("preparing")
        with patch.object(host, "inspect", return_value={"Id": before()["container"]}):
            self.assertEqual(self.h.recover(plan()), before())
        self.h.ctl.activate.assert_not_called()
        self.assertFalse((host.STATE / "reservation.json").exists())

    def test_recovered_retry_does_not_delete_new_reservation(self):
        self.journal("recovered")
        other = {"release": "20261117_130000", "identity": "other"}
        host.atomic(host.STATE / "reservation.json", other)
        self.h.recover(plan())
        self.assertEqual(json.loads((host.STATE / "reservation.json").read_text()), other)

    def test_other_candidate_reservation_blocks_ready_recover_and_close(self):
        self.journal()
        host.atomic(host.STATE / "reservation.json", {"release": "other", "identity": "other"})
        for method in (self.h.ready, self.h.recover, self.h.close):
            with self.subTest(method=method), self.assertRaises(ValueError):
                method(plan())

    def test_expired_ready_or_replaced_container_refused(self):
        journal = self.journal()
        with patch.object(host.time, "time", return_value=journal["ready_at"] + 3601), self.assertRaises(ValueError):
            self.h.ready(plan())
        with patch.object(host, "inspect", return_value={"Id": "replacement", "State": {"Running": True}}):
            with self.assertRaises(ValueError):
                self.h.ready(plan())

    def test_crashed_candidate_never_receives_traffic(self):
        self.journal()
        image = {"Id": "image", "Config": {"Cmd": ["default"], "Entrypoint": None}}
        candidate = {"Id": "new", "Image": "image", "Config": {"Cmd": ["default"], "Entrypoint": None,
                     "Env": ["ENV=production"]}, "RestartCount": 1,
                     "State": {"Running": True, "OOMKilled": False}}
        with patch.object(host, "inspect", side_effect=[candidate, image]), self.assertRaises(ValueError):
            self.h.activate(plan())
        self.h.ctl.activate.assert_not_called()

    def test_wrong_candidate_release_refused_before_switch(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"release":"unknown"}'))
        response.__exit__ = Mock(return_value=False)
        opened = io.BytesIO(b'{"release":"unknown"}')
        opened.status = 200
        with patch.object(host.urllib.request, "urlopen", return_value=opened), self.assertRaises(ValueError):
            host.reported_release("http://127.0.0.1:18002/ready", plan()["release"])

    def test_published_completion_is_idempotent_and_not_rollbackable(self):
        self.journal("complete")
        other = {"release": "other", "identity": "other"}
        host.atomic(host.STATE / "reservation.json", other)
        self.assertEqual(self.h.complete(plan()), {"complete": True})
        self.assertEqual(json.loads((host.STATE / "reservation.json").read_text()), other)
        with self.assertRaises(ValueError):
            self.h.recover(plan())

    def test_startup_writes_overrides_restart_or_oom_refused(self):
        image = {"Id": "image", "Config": {"Cmd": ["default"], "Entrypoint": None}}
        container = {"Image": "image", "Config": {"Cmd": ["default"], "Entrypoint": None,
                     "Env": ["ENV=production", "RUN_SEED_ON_STARTUP=false"]},
                     "RestartCount": 0, "State": {"Running": True, "OOMKilled": False}}
        host.assert_runtime(container, image)
        for mutate in (lambda c: c["Config"].update(Cmd=["override"]),
                       lambda c: c["Config"]["Env"].append("RUN_SEED_ON_STARTUP=true"),
                       lambda c: c.update(RestartCount=1), lambda c: c["State"].update(OOMKilled=True)):
            changed = copy.deepcopy(container)
            mutate(changed)
            with self.assertRaises(ValueError):
                host.assert_runtime(changed, image)

    def test_controller_child_process_output_stays_out_of_protocol(self):
        controller = self.root / "controller.py"
        controller.write_text("def run(*args, capture=False):\n    raise AssertionError('must be replaced')\n")
        with patch.object(host, "trusted"):
            h = host.Host({"role": "backend", "controller": str(controller), "controller_sha256": "hash"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(h.ctl.run(sys.executable, "-c", "print('child output')", capture=True), "child output")
            self.assertEqual(h.ctl.run(sys.executable, "-c", "print('hidden')"), "")
        self.assertEqual(out.getvalue(), "")

    @unittest.skipIf(sys.platform == "win32", "Target is Linux; Windows symlink creation needs elevation")
    def test_source_pointer_retries_replace_symlinks_atomically(self):
        self.h.point_current("20261117_120000")
        self.assertTrue((self.root / "current").is_symlink())
        self.h.point_current("20261116_130518")
        self.h.point_current("20261116_130518")
        self.assertEqual((self.root / "current").readlink(), self.root / "releases/20261116_130518")

    def test_completed_journal_retry_releases_only_its_own_interrupted_reservation(self):
        self.journal("complete")
        self.h.complete(plan())
        self.assertFalse((host.STATE / "reservation.json").exists())


class FakeRemote:
    def __init__(self):
        self.events = []
        self.fail = None

    def transfer(self, role, plan, source):
        self.events.append((role, "upload"))

    def call(self, role, action, plan=None):
        self.events.append((role, action))
        if self.fail == (role, action):
            raise RuntimeError("injected failure")
        return before(role) if action == "snapshot" else {"ok": True}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.github = Mock()
        self.github.head.return_value = "old-integration"
        self.remote = FakeRemote()
        self.w = worker.Worker(self.github, self.remote, Path(self.temporary.name) / "state.json")

    def ready(self):
        self.w.checkpoint("ready", plan=plan(), branch="codex/task", integration_before="old-integration")

    def test_untrusted_workflow_event_and_fork_refused(self):
        run = {"event": "push", "status": "completed", "conclusion": "success", "head_branch": "codex/task",
               "head_repository": {"full_name": worker.REPOSITORY}, "path": ".github/workflows/ci.yml"}
        self.assertTrue(worker.eligible_run(run))
        for change in ({"event": "pull_request"}, {"conclusion": "failure"}, {"head_branch": "main"},
                       {"path": ".github/workflows/evil.yml"}, {"head_repository": {"full_name": "fork/ERP"}}):
            self.assertFalse(worker.eligible_run({**run, **change}))

    def test_deleted_historical_branch_is_skipped_but_auth_errors_are_not(self):
        run = {"id": 123, "head_sha": plan()["commit"], "event": "push", "status": "completed",
               "conclusion": "success", "head_branch": "codex/deleted", "path": ".github/workflows/ci.yml",
               "head_repository": {"full_name": worker.REPOSITORY}}
        self.github.api.return_value = {"workflow_runs": [run]}
        self.github.head.side_effect = HTTPError("url", 404, "deleted", {}, None)
        self.assertIsNone(self.w.find())
        self.github.head.side_effect = HTTPError("url", 403, "forbidden", {}, None)
        with self.assertRaises(HTTPError):
            self.w.find()

    def test_stale_baseline_refusal_never_starts_host_changes(self):
        original = self.remote.call
        self.remote.call = lambda role, action, plan=None: (
            {**before(role), "release": "new-production"} if action == "snapshot" else original(role, action, plan))
        self.w.prepare({"id": 123, "head_branch": "codex/task"}, plan(), b"archive")
        self.assertEqual(self.w.state["phase"], "idle")
        self.assertFalse(self.remote.events)
        self.assertIn(123, self.w.state["seen"])

    def test_preparation_and_activation_order(self):
        self.w.prepare({"id": 123, "head_branch": "codex/task"}, plan(), b"archive")
        events = self.remote.events
        self.assertLess(events.index(("backend", "prepare")), events.index(("frontend", "prepare")))
        self.assertNotIn(("backend", "activate"), events)
        self.github.head.return_value = "merged"
        self.github.tree.return_value = plan()["tree"]
        self.w.public_checks = Mock()
        self.w.activate("merged")
        self.assertLess(events.index(("backend", "activate")), events.index(("frontend", "activate")))
        self.assertEqual(self.w.state["phase"], "live")

    def test_backend_failure_never_switches_frontend_and_both_recover(self):
        self.ready()
        self.github.head.return_value = "merged"
        self.github.tree.return_value = plan()["tree"]
        self.remote.fail = ("backend", "activate")
        with self.assertRaises(RuntimeError):
            self.w.activate("merged")
        self.assertNotIn(("frontend", "activate"), self.remote.events)
        self.remote.fail = None
        self.w.recover()
        self.assertIn(("backend", "recover"), self.remote.events)
        self.assertIn(("frontend", "recover"), self.remote.events)

    def test_one_recovery_failure_does_not_skip_other_host(self):
        self.ready()
        self.remote.fail = ("backend", "recover")
        with self.assertRaises(RuntimeError):
            self.w.recover()
        self.assertIn(("frontend", "recover"), self.remote.events)
        self.assertEqual(self.w.state["phase"], "recovery_required")

    def test_merged_source_must_match_entire_tested_tree(self):
        self.ready()
        self.github.tree.return_value = "different"
        with self.assertRaises(ValueError):
            self.w.activate("merged")
        self.assertNotIn(("backend", "activate"), self.remote.events)

    def test_deleted_source_branch_does_not_block_exact_merge(self):
        self.ready()
        self.github.head.side_effect = lambda branch: "merged" if branch == "clone_main" else (_ for _ in ()).throw(KeyError("deleted"))
        self.w.activate = Mock()
        self.w.tick()
        self.w.activate.assert_called_once_with("merged")

    def test_crash_is_not_silently_resumed_as_success(self):
        self.w.checkpoint("activating", plan=plan())
        restarted = worker.Worker(self.github, self.remote, self.w.state_path)
        with self.assertRaises(ValueError):
            restarted.tick()
        self.assertEqual(self.remote.events, [])

    def test_metadata_publication_uses_merged_ancestry_and_fast_forward_cas(self):
        self.w.checkpoint("publishing", plan=plan(), merged_sha="squashed-integration",
                          activated_at="2026-11-17T12:00:00+00:00", closing_snapshot={})
        self.github.head.return_value = "squashed-integration"
        import base64
        context = base64.b64encode(b"Last updated 2026-11-16.\n\n## Existing context\nkeep me\n").decode()
        answers = iter(({"content": context}, {"sha": "blob"}, {"sha": "context"}, {"sha": "evidence"},
                        {"sha": "new-tree"}, {"sha": "baseline-commit"}, {}))
        self.github.api.side_effect = lambda *args, **kwargs: next(answers)
        self.assertEqual(self.w.publish_baseline(plan()), "baseline-commit")
        payload = self.github.api.call_args_list[1].args[1]
        baseline = json.loads(payload["content"])
        self.assertEqual(baseline["git_baseline_commit"], "squashed-integration")
        self.assertEqual(baseline["runtime_git_commit"], plan()["commit"])
        final = self.github.api.call_args_list[-1]
        self.assertEqual(final.args[1], {"sha": "baseline-commit", "force": False})

    def test_api_success_before_checkpoint_is_idempotent(self):
        self.w.checkpoint("publishing", plan=plan(), merged_sha="merged",
                          activated_at="2026-11-17T12:00:00+00:00", closing_snapshot={})
        self.github.head.return_value = "already-published"
        import base64
        context = base64.b64encode(b"Last updated 2026-11-16.\n\n## Existing context\n").decode()
        answers = iter(({"content": context}, {"sha": "blob"}, {"sha": "context"}, {"sha": "evidence"}, {"sha": "new-tree"},
                        {"tree": {"sha": "new-tree"}, "parents": [{"sha": "merged"}]}))
        self.github.api.side_effect = lambda *args, **kwargs: next(answers)
        self.assertEqual(self.w.publish_baseline(plan()), "already-published")
        self.assertFalse(any(call.kwargs.get("method") == "PATCH" for call in self.github.api.call_args_list))

    def test_published_baseline_can_only_finalize_not_recover(self):
        self.w.checkpoint("finalizing", plan=plan(), baseline_commit="published")
        with self.assertRaises(ValueError):
            self.w.recover()
        self.w.tick()
        self.assertEqual(self.w.state["phase"], "idle")
        self.assertIn(("backend", "complete"), self.remote.events)
        self.assertNotIn(("backend", "recover"), self.remote.events)


if __name__ == "__main__":
    unittest.main()
