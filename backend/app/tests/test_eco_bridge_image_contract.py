"""Fault-inject the real Docker gate orchestration without Docker or SSH."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "test_eco_bridge_image.py"
spec = importlib.util.spec_from_file_location("eco_bridge_image_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
IMAGE = "ghcr.io/shmirzaev/milana-erp-backend@sha256:" + "2" * 64
COMMIT = "a" * 40


class FakeProof(gate.BridgeImageProof):
    def __init__(self, fault=None):
        super().__init__(IMAGE, COMMIT)
        self.fault, self.calls, self.containers, self.networks = fault, [], {}, {}
        self.revision = None
        self.image_info = dict(Id="sha256:" + "3" * 64, RepoDigests=[IMAGE],
            Config=dict(Cmd=["default"], Entrypoint=None, Labels={"org.opencontainers.image.revision": COMMIT}))

    def inspect(self, kind, name):
        return deepcopy((self.containers if kind == "container" else self.networks).get(name))

    def wait_for(self, probe, seconds):
        return probe()

    def docker(self, *args, env=None, timeout=45):
        self.calls.append(args)
        assert not any(arg in args for arg in ("--env-file", "--publish", "-p", "-v", "--volume", "--privileged"))
        if args[0] == "pull":
            return "pulled"
        if args[:2] == ("image", "inspect"):
            value = deepcopy(self.image_info)
            if args[2] == gate.POSTGRES:
                value["RepoDigests"] = [gate.POSTGRES]
            elif self.fault == "image":
                value["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
            return json.dumps([value])
        if args[:2] == ("network", "create"):
            self.networks[self.network] = dict(Id="network-id", Labels={gate.LABEL: self.owner}, Internal=True, Driver="bridge")
            return "network-id"
        if args[0] == "run":
            name = args[args.index("--name") + 1]
            values = {args[i + 1]: env[args[i + 1]] for i, value in enumerate(args) if value == "--env"}
            if "--entrypoint" in args:
                assert "migration" in name
                self.revision = args[-1].split()[-1]
            elif "backend" in name:
                assert args[-1] == IMAGE  # Actual image default; no appended command.
                if self.fault == "auto_upgrade" and self.revision == gate.PREDECESSOR:
                    self.revision = gate.SUCCESSOR
            self.containers[name] = dict(Id=name + "-id", Image=self.image_info["Id"], RestartCount=0,
                Config=dict(Cmd=self.image_info["Config"]["Cmd"], Entrypoint=None,
                    Labels={gate.LABEL: self.owner}, Env=[key + "=" + value for key, value in values.items()]),
                HostConfig=dict(RestartPolicy={"Name": "no"}, Memory=1073741824, PidsLimit=256,
                    PortBindings={}, PublishAllPorts=False, Binds=None, Privileged=False), Mounts=[],
                State=dict(Running=True, OOMKilled=False), NetworkSettings={"Networks": {self.network: {}}})
            if self.fault == "cmd" and "backend" in name:
                self.containers[name]["Config"]["Cmd"] = ["overridden"]
            return name + "-id"
        if args[0] == "exec":
            if args[-1] == gate.HTTP and self.fault == "health":
                raise RuntimeError("Injected unhealthy default CMD")
            if gate.SCHEMA_PROOF in args:
                assert self.revision == args[-1], "Auto-migration changed predecessor"
                return json.dumps(dict(revision=self.revision, eco_tables=[] if self.revision == gate.PREDECESSOR else list(gate.TABLES)))
            return "healthy"
        if args[0] == "wait":
            return "1" if self.fault == "migration" else "0"
        if args[0] == "top":
            return "1 spawn_main\n2 spawn_main"
        if args[0] in ("container", "network") and args[1] == "rm":
            store = self.containers if args[0] == "container" else self.networks
            name = next(key for key, value in store.items() if value["Id"] == args[-1])
            del store[name]
            return "removed"
        raise AssertionError(args)

    def logs(self, *args, **kwargs):
        marker = ("startup: verified empty ECO rollback predecessor accepted (" if self.revision == gate.PREDECESSOR else "startup: database migration head verified (") + self.revision + ")"
        return SimpleNamespace(stdout=(marker + "\n") * 2, stderr="", returncode=0)


def test_exact_default_image_checks_both_actual_schema_phases_and_cleans():
    proof = FakeProof()
    with patch.object(gate.subprocess, "run", side_effect=proof.logs):
        result = proof.run()
    assert result["passed"]
    assert [phase["revision"] for phase in result["phases"]] == [gate.PREDECESSOR, gate.SUCCESSOR]
    assert all(phase["workers"] == 2 and phase["marker_count"] == 2 for phase in result["phases"])
    assert not proof.containers and not proof.networks
    assert proof.env["RUN_SEED_ON_STARTUP"] == proof.env["STARTUP_SCHEMA_SYNC"] == "false"
    assert proof.env["JWT_SECRET"] != proof.env["FILE_SIGNING_SECRET"]
    assert proof.env["JWT_SECRET"] not in json.dumps(result)


@pytest.mark.parametrize("fault", ["image", "migration", "health", "cmd", "auto_upgrade"])
def test_failed_image_migration_default_command_or_health_never_passes_and_cleans(fault):
    proof = FakeProof(fault)
    with patch.object(gate.subprocess, "run", side_effect=proof.logs), pytest.raises((AssertionError, RuntimeError)):
        proof.run()
    assert not proof.containers and not proof.networks


def test_foreign_resource_cannot_be_removed():
    proof = FakeProof()
    proof.containers["foreign"] = dict(Id="foreign-id", Config={"Labels": {gate.LABEL: "foreign"}})
    with pytest.raises(AssertionError, match="foreign"):
        proof.remove("container", "foreign")
    assert not proof.calls


def test_http_ready_first_worker_waits_for_second_worker_and_startup_marker():
    class DelayedProof(FakeProof):
        top_calls, log_calls = 0, 0

        def wait_for(self, probe, seconds):
            return gate.BridgeImageProof.wait_for(probe, seconds)

        def docker(self, *args, **kwargs):
            if args[0] == "top":
                self.top_calls += 1
                if self.top_calls == 1:
                    return "1 spawn_main"
            return super().docker(*args, **kwargs)

        def logs(self, *args, **kwargs):
            self.log_calls += 1
            result = super().logs(*args, **kwargs)
            if self.log_calls == 1:
                result.stdout = result.stdout.splitlines()[0]
            return result

    proof = DelayedProof()
    with patch.object(gate.subprocess, "run", side_effect=proof.logs), patch.object(gate.time, "sleep") as sleep:
        result = proof.run()
    assert result["passed"] and proof.top_calls >= 5
    sleep.assert_called_once_with(1)


def test_fatal_startup_log_error_is_not_retried():
    def failure():
        raise gate.StartupError("Injected fatal startup error")
    with patch.object(gate.time, "sleep") as sleep, pytest.raises(gate.StartupError):
        gate.BridgeImageProof.wait_for(failure, 120)
    sleep.assert_not_called()


def test_image_gate_is_mandatory_before_release_artifact_upload():
    import yaml
    workflow = yaml.safe_load((SCRIPT.parents[1] / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["release"]["steps"]
    index = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Prove bridge image default CMD"))
    assert index > next(i for i, step in enumerate(steps) if step.get("id") == "backend_image")
    assert index < next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact"))
    assert "if" not in steps[index] and not steps[index].get("continue-on-error")
    assert "steps.backend_image.outputs.digest" in steps[index]["env"]["BRIDGE_IMAGE"]
