#!/usr/bin/env python3
"""Fixed LAN deployment worker: consume verified GitHub data, never workflow code.

Run as a dedicated unprivileged account with its own SSH key and fine-grained
GitHub token. The installed program is updated only by an administrator.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import re
import urllib.error
import urllib.request
import zipfile

from release_manifest import BRANCH, CI_POLICY_PATHS, HEX64, REPOSITORY, validate

MAX_DOWNLOAD = 128 * 1024 * 1024
HELPER = "sudo -n /usr/bin/python3 -E -s /opt/milana-erp/shared/deploy/auto_release_host.py"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token, policy=None):
        self.token = token
        self.policy = policy or {}

    def verify_recipe(self, commit):
        # A success badge from a branch that rewrote its tests/scan job is not evidence.
        if set(self.policy) != set(CI_POLICY_PATHS) or any(not HEX64.fullmatch(digest) for digest in self.policy.values()):
            raise ValueError("Installed CI policy pins are missing/invalid")
        for path, expected in self.policy.items():
            content = self.api(f"contents/{path}?ref={commit}")
            if content.get("encoding") != "base64":
                raise ValueError("Unexpected CI recipe encoding")
            if hashlib.sha256(base64.b64decode(content["content"])).hexdigest() != expected:
                raise ValueError("CI policy changed; administrator review/repinning required")

    def api(self, path, payload=None, method=None):
        url = f"https://api.github.com/repos/{REPOSITORY}/{path}"
        request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                         method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "milana-fixed-deployer",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def download(self, artifact):
        # Never forward the API token to Azure/object-storage redirect targets.
        url = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}",
                                                       "User-Agent": "milana-fixed-deployer"})
        try:
            response = urllib.request.build_opener(NoRedirect()).open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code != 302:
                raise
            from urllib.parse import urlsplit
            location = exc.headers["Location"]
            parsed = urlsplit(location)
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(
                (".blob.core.windows.net", ".actions.githubusercontent.com", ".githubusercontent.com")
            ):
                raise ValueError("Unexpected artifact storage redirect") from None
            response = urllib.request.build_opener(NoRedirect()).open(
                urllib.request.Request(location, headers={"User-Agent": "milana-fixed-deployer"}), timeout=60)
        with response:
            data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD or artifact.get("digest") != "sha256:" + hashlib.sha256(data).hexdigest():
            raise ValueError("GitHub artifact checksum/size mismatch")
        return data

    def pages(self, path, key):
        rows = []
        for page in range(1, 101):
            separator = "&" if "?" in path else "?"
            batch = self.api(f"{path}{separator}per_page=100&page={page}")[key]
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise ValueError("GitHub pagination exceeded the bounded limit")

    def status(self, commit, state, description, run_id):
        self.api(f"statuses/{commit}", {"state": state, "context": "Milana / production",
                 "description": description[:140],
                 "target_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"})

    def tree(self, sha):
        return self.api(f"git/commits/{sha}")["tree"]["sha"]

    def head(self, branch):
        return self.api(f"git/ref/heads/{branch}")["object"]["sha"]


def eligible_run(run):
    return (run.get("event") == "push" and run.get("status") == "completed"
            and run.get("conclusion") == "success" and run.get("head_branch", "").startswith("codex/")
            and run.get("head_repository", {}).get("full_name") == REPOSITORY
            and run.get("path") == ".github/workflows/ci.yml")


def read_bundle(data, run):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError("Duplicate artifact entries")
        if sum(entry.file_size for entry in entries) > MAX_DOWNLOAD:
            raise ValueError("Expanded artifact too large")
        plan = validate(json.loads(archive.read("deployment.json")))
        expected = {"deployment.json", f"milana-erp-{plan['release']}.tar.gz",
                    f"milana-erp-{plan['release']}.tar.gz.json"}
        if {entry.filename for entry in entries} != expected:
            raise ValueError("Unexpected artifact contents")
        source = archive.read(f"milana-erp-{plan['release']}.tar.gz")
    if plan["run_id"] != run["id"] or plan["commit"] != run["head_sha"]:
        raise ValueError("Artifact belongs to another run/source")
    if hashlib.sha256(source).hexdigest() != plan["archive_sha256"]:
        raise ValueError("Source archive checksum mismatch")
    return plan, source


class Remote:
    def __init__(self, config):
        self.config = config

    def ssh(self, role):
        return ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={self.config['known_hosts']}",
                "-o", "ConnectTimeout=10", "-i", self.config["ssh_key"], self.config["hosts"][role]]

    def call(self, role, action, plan=None):
        result = subprocess.run(self.ssh(role) + [HELPER],
                                input=json.dumps({"action": action, "plan": plan}).encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        if result.returncode:
            raise RuntimeError(f"{role} {action} failed; inspect the protected host journal")
        receipt = json.loads(result.stdout)
        if receipt.get("ok") is not True:
            raise RuntimeError(f"{role} refused {action}")
        return receipt["result"]

    def transfer(self, role, plan, source):
        name = f"/var/lib/milana-auto-release/inbox/{plan['release']}.tar.gz"
        # A fixed restricted path and validated release ID; no caller-controlled shell text.
        result = subprocess.run(self.ssh(role) + [f"umask 077; set -C; cat > {name}"], input=source,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if result.returncode:
            raise RuntimeError(f"{role} source upload refused")


class Worker:
    def __init__(self, github, remote, state_path):
        self.github = github
        self.remote = remote
        self.state_path = state_path
        self.state = json.loads(state_path.read_text()) if state_path.exists() else {"phase": "idle", "seen": []}

    def checkpoint(self, phase, **values):
        self.state.update(values, phase=phase)
        save(self.state_path, self.state)

    def both(self, action, plan):
        # Always join both futures: retain both outcomes even if the first host fails.
        outcomes, failures = {}, []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {role: pool.submit(self.remote.call, role, action, plan) for role in ("backend", "frontend")}
            for role, future in pending.items():
                try:
                    outcomes[role] = future.result()
                except Exception:
                    failures.append(role)
        if failures:
            raise RuntimeError(f"{action} failed on {', '.join(failures)}")
        return outcomes

    def find(self):
        runs = self.github.api("actions/workflows/ci.yml/runs?event=push&status=success&per_page=30")["workflow_runs"]
        for run in runs:
            if not eligible_run(run) or run["id"] in self.state["seen"]:
                continue
            try:
                head = self.github.head(run["head_branch"])
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue  # Merged/deleted branches remain in historical workflow runs.
                raise
            if head != run["head_sha"]:
                continue
            permission = self.github.api(f"collaborators/{run['actor']['login']}/permission")["permission"]
            if permission not in {"admin", "maintain", "write"}:
                continue
            jobs = self.github.pages(f"actions/runs/{run['id']}/jobs?filter=latest", "jobs")
            for required in ("backend", "frontend", "security-scan / scan", "release"):
                if not any(job["name"] == required and job["conclusion"] == "success" for job in jobs):
                    raise ValueError("Candidate has missing/skipped required jobs")
            artifacts = self.github.pages(f"actions/runs/{run['id']}/artifacts", "artifacts")
            bundles = [item for item in artifacts if item["name"].startswith("milana-erp-") and not item["expired"]]
            if len(bundles) != 1:
                continue
            plan, source = read_bundle(self.github.download(bundles[0]), run)
            if self.github.tree(plan["commit"]) != plan["tree"]:
                raise ValueError("Artifact tree differs from GitHub source tree")
            self.github.verify_recipe(plan["commit"])
            ancestry = self.github.api(f"compare/{plan['base']['git_baseline_commit']}...{plan['commit']}")
            if ancestry["status"] not in {"ahead", "identical"}:
                raise ValueError("Candidate does not descend from the production baseline")
            return run, plan, source
        return None

    def prepare(self, run, plan, source):
        # Drift refusal before any host change must not create a recovery incident.
        for snapshot in self.both("snapshot", plan).values():
            if any(snapshot[key] != plan["base"][key] for key in ("release", "source_manifest_sha256")) or (
                snapshot["schema_fingerprint"] != plan["schema_fingerprint"]
            ):
                self.checkpoint("idle", seen=[*self.state["seen"][-199:], run["id"]])
                self.github.status(plan["commit"], "failure", "Baseline/schema changed — reconcile and push a fresh candidate",
                                   plan["run_id"])
                return
        self.checkpoint("preparing", plan=plan, branch=run["head_branch"],
                        integration_before=self.github.head(BRANCH),
                        seen=[*self.state["seen"][-199:], run["id"]])
        self.github.status(plan["commit"], "pending", "Preparing servers; production unchanged", plan["run_id"])
        for role in ("backend", "frontend"):
            self.remote.transfer(role, plan, source)
        # Backup on backend must pass before either candidate starts.
        self.remote.call("backend", "prepare", plan)
        self.remote.call("frontend", "prepare", plan)
        self.both("ready", plan)
        self.checkpoint("ready")
        self.github.status(plan["commit"], "success", "Ready to deploy — merge this exact candidate into clone_main",
                           plan["run_id"])

    def activate(self, merged_sha):
        plan = self.state["plan"]
        # A merge/squash/rebase is acceptable only when its ENTIRE source tree is identical.
        if self.github.tree(merged_sha) != plan["tree"] or self.github.head(BRANCH) != merged_sha:
            raise ValueError("Integration source changed; prepare and validate the combined source")
        self.both("ready", plan)
        if self.github.head(BRANCH) != merged_sha:
            raise ValueError("Integration changed immediately before cutover")
        self.checkpoint("activating", merged_sha=merged_sha)
        self.github.status(plan["commit"], "pending", "Activating prepared release", plan["run_id"])
        self.remote.call("backend", "activate", plan)
        self.remote.call("frontend", "activate", plan)
        self.both("postflight", plan)
        self.public_checks(plan)
        self.checkpoint("live", activated_at=datetime.now(timezone.utc).isoformat())
        self.github.status(plan["commit"], "pending", "Live — observation in progress", plan["run_id"])

    def public_checks(self, plan):
        from urllib.request import Request
        for url, method in (("http://172.16.10.4:8000/health", "GET"),
                            ("http://172.16.10.5:3000/login", "HEAD"),
                            ("https://erp.milanapremium.uz/health", "GET"),
                            ("https://erp.milanapremium.uz/login", "HEAD")):
            with urllib.request.build_opener(NoRedirect()).open(Request(url, method=method), timeout=10) as response:
                if response.status != 200:
                    raise ValueError("Postflight endpoint failed")
                if url.endswith("/health") and json.load(response).get("release") != plan["release"]:
                    raise ValueError("Served release identity mismatch")

    def finish(self):
        plan = self.state["plan"]
        # The installed observer is reviewed with this worker, never loaded from a candidate.
        observer = Path(__file__).with_name("observe_release.py")
        evidence = self.state_path.parent / f"{plan['release']}-observation.json"
        self.checkpoint("observing")
        result = subprocess.run([sys.executable, str(observer), "--release", plan["release"],
                                 "--commit", plan["commit"], "--risk", "high",
                                 "--reason", "Automatic release; conservative observation window",
                                 "--output", str(evidence)], timeout=1900)
        if result.returncode:
            raise ValueError("Observation failed/interrupted; preserve original evidence")
        self.checkpoint("closing")
        self.finalize()

    def finalize(self):
        plan = self.state["plan"]
        if self.state["phase"] == "closing":
            self.public_checks(plan)
            self.both("postflight", plan)
            snapshots = self.both("close", plan)
            self.checkpoint("publishing", closing_snapshot=snapshots)
        if self.state["phase"] == "publishing":
            published = self.publish_baseline(plan)
            self.checkpoint("finalizing", baseline_commit=published)
        # Retry metadata/terminal work after a crash; NEVER roll back published baseline.
        self.both("complete", plan)
        self.github.status(plan["commit"], "success", "Live — observation and closing checks passed", plan["run_id"])
        self.checkpoint("idle")

    def publish_baseline(self, plan):
        expected = self.state["merged_sha"]
        baseline = {**plan["base"], "release": plan["release"],
                    "source_manifest_sha256": plan["source_manifest_sha256"],
                    "git_baseline_commit": expected, "runtime_git_commit": plan["commit"]}
        content = json.dumps(baseline, indent=2) + "\n"
        date = datetime.fromisoformat(self.state["activated_at"]).astimezone(timezone(timedelta(hours=5))).date()
        previous = self.github.api(f"contents/docs/PROJECT_CONTEXT.md?ref={expected}")
        context = base64.b64decode(previous["content"]).decode()
        context = re.sub(r"Last updated:? [0-9]{4}-[0-9]{2}-[0-9]{2}", f"Last updated {date}", context, count=1)
        note = (f"## Automatic release {plan['release']} ({date})\n\n"
                f"Runtime commit `{plan['commit']}`, accepted integration `{expected}`, manifest "
                f"`{plan['source_manifest_sha256']}`. Previous application `{plan['base']['release']}` "
                "is retained for rollback. Schema history unchanged; no migration or release business-data writes. "
                "Exact-source CI, installed site gates, four endpoints, 30-minute health observation and closing "
                f"checks passed. See [immutable release evidence](archive/AUTO_RELEASE_{plan['release']}.json).\n\n")
        anchor = context.find("\n## ", context.find("Last updated"))
        if anchor < 0:
            raise ValueError("Project context layout changed; reconcile publication")
        context = context[:anchor + 1] + note + context[anchor + 1:]
        evidence = {"plan": plan, "integration_commit": expected, "activated_at": self.state["activated_at"],
                    "roles": self.state["closing_snapshot"], "observation": "passed; protected full receipt retained on worker"}
        updates = {"deploy/production-base.json": content, "docs/PROJECT_CONTEXT.md": context,
                   f"docs/archive/AUTO_RELEASE_{plan['release']}.json": json.dumps(evidence, indent=2) + "\n"}
        nodes = []
        for path, body in updates.items():
            blob = self.github.api("git/blobs", {"content": body, "encoding": "utf-8"})["sha"]
            nodes.append({"path": path, "mode": "100644", "type": "blob", "sha": blob})
        tree = self.github.api("git/trees", {"base_tree": plan["tree"], "tree": nodes})["sha"]
        current = self.github.head(BRANCH)
        if current != expected:
            actual = self.github.api(f"git/commits/{current}")
            if actual["tree"]["sha"] == tree and [p["sha"] for p in actual["parents"]] == [expected]:
                return current  # API update succeeded before the worker checkpoint/crash.
            raise ValueError("Integration advanced; reconcile baseline publication without rolling back live")
        commit = self.github.api("git/commits", {"message": f"docs: record automatic release {plan['release']}",
                                                "tree": tree, "parents": [expected]})["sha"]
        # force=false rejects concurrent pushes because the new commit has only expected as parent.
        self.github.api(f"git/refs/heads/{BRANCH}", {"sha": commit, "force": False}, method="PATCH")
        return commit

    def recover(self):
        if self.state["phase"] in {"publishing", "finalizing", "idle"}:
            raise ValueError("This phase permits finalization retry, not rollback")
        plan = self.state["plan"]
        failures = []
        # Attempt BOTH roles independently, backend first, even if one refuses recovery.
        for role in ("backend", "frontend"):
            try:
                self.remote.call(role, "recover", plan)
            except Exception:
                failures.append(role)
        self.checkpoint("recovery_required" if failures else "idle")
        if failures:
            raise RuntimeError("Recovery requires operator inspection on " + ", ".join(failures))

    def tick(self):
        phase = self.state["phase"]
        if phase == "idle":
            candidate = self.find()
            if candidate:
                self.prepare(*candidate)
        elif phase == "ready":
            plan = self.state["plan"]
            merged = self.github.head(BRANCH)
            if merged != self.state["integration_before"]:
                self.activate(merged)
            elif self.github.head(self.state["branch"]) != plan["commit"]:
                self.recover()  # Superseded before cutover; release this reservation safely.
                self.github.status(plan["commit"], "failure", "Superseded by a newer push; waiting for its checks",
                                   plan["run_id"])
        elif phase == "live":
            self.finish()
        elif phase in {"closing", "publishing", "finalizing"}:
            self.finalize()
        else:
            raise ValueError("Interrupted deployment; inspect journals and run explicit --recover")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/milana-auto-release/worker.json"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    state = Path(config["state_directory"])
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl
    with (state / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker = Worker(GitHub(Path(config["token_file"]).read_text().strip(), config["policy_sha256"]),
                        Remote(config), state / "state.json")
        if args.recover:
            worker.recover()
            return
        while True:
            try:
                worker.tick()
            except Exception as exc:
                # Keep the cause category but never dump tokens, signed URLs, subprocess/env output.
                print(json.dumps({"phase": worker.state["phase"], "error": type(exc).__name__}), flush=True)
                if worker.state["phase"] != "idle":
                    if worker.state["phase"] not in {"closing", "publishing", "finalizing"}:
                        worker.checkpoint("recovery_required")
                    plan = worker.state.get("plan")
                    if plan:
                        worker.github.status(plan["commit"], "failure", "Stopped — inspect deployment journals",
                                             plan["run_id"])
                    raise SystemExit(2) from None
            if args.once:
                return
            time.sleep(5)


if __name__ == "__main__":
    main()
