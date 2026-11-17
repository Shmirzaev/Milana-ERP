#!/usr/bin/env python3
"""Install reviewed fixed tooling. Dry-run unless --apply; never start a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def copy_atomic(source, target, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".install-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.chown(name, 0, 0)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("backend", "frontend", "worker"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--account", default="milana-deploy")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    config = json.loads(args.config.read_text())
    if args.role == "worker":
        from release_manifest import CI_POLICY_PATHS
        # Read from this administrator-reviewed checkout, never a downloaded candidate.
        config["policy_sha256"] = {path: hashlib.sha256((source.parent / path).read_bytes()).hexdigest()
                                   for path in CI_POLICY_PATHS}
        target = Path("/opt/milana-auto-release")
        files = {"auto_release_worker.py": source / "auto_release_worker.py",
                 "release_manifest.py": source / "release_manifest.py",
                 "observe_release.py": source.parent / "scripts/observe_release.py"}
        config_target = Path("/etc/milana-auto-release/worker.json")
    else:
        if config["role"] != args.role:
            parser.error("Configuration role does not match this host")
        from auto_release_host import trusted
        trusted(Path(config["controller"]), config["controller_sha256"])
        trusted(Path(config["gate"]), config["gate_sha256"])
        target = Path("/opt/milana-erp/shared/deploy")
        files = {name: source / name for name in ("auto_release_host.py", "release_manifest.py")}
        config_target = Path("/etc/milana-auto-release/host.json")
        executables = ["docker", "haproxy", "sudo", "visudo"]
        if args.role == "backend":
            executables += ["pg_dump", "pg_restore"]
        for executable in executables:
            if not shutil.which(executable):
                parser.error(f"Required installed executable is missing: {executable}")
    print(json.dumps({"apply": args.apply, "role": args.role, "files": [str(target / p) for p in files],
                      "configuration": str(config_target), "starts_worker": False, "deploys_release": False}))
    if not args.apply:
        return
    if os.geteuid() != 0:
        parser.error("Installation requires an administrator")
    import pwd
    account = pwd.getpwnam(args.account)
    if not account.pw_uid:
        parser.error("Worker/SSH account must not be root")
    # Never replace installed code underneath an in-flight deployment.
    reservation = Path("/opt/milana-erp/runtime/auto-release/reservation.json")
    worker_state = Path(config.get("state_directory", "/var/lib/milana-auto-release/state")) / "state.json"
    if reservation.exists() or (worker_state.exists() and json.loads(worker_state.read_text())["phase"] != "idle"):
        parser.error("An automatic release is reserved/in progress; finish or recover it before upgrading tooling")
    if args.role == "worker" and subprocess.run(
        ["systemctl", "is-active", "--quiet", "milana-auto-release"], check=False
    ).returncode == 0:
        parser.error("Stop the worker service before changing its installed code")
    for name, path in files.items():
        copy_atomic(path, target / name)
    with tempfile.TemporaryDirectory() as directory:
        prepared = Path(directory) / "config.json"
        prepared.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        copy_atomic(prepared, config_target, 0o640)
    os.chown(config_target, 0, account.pw_gid if args.role == "worker" else 0)
    if args.role == "worker":
        for name in ("state", "credentials"):
            directory = Path("/var/lib/milana-auto-release") / name
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)
            os.chown(directory, account.pw_uid, account.pw_gid)
        copy_atomic(source / "auto-release-worker.service", Path("/etc/systemd/system/milana-auto-release.service"))
        subprocess.run(["systemctl", "daemon-reload"], check=True)
    else:
        inbox = Path("/var/lib/milana-auto-release/inbox")
        inbox.mkdir(mode=0o700, parents=True, exist_ok=True)
        inbox.chmod(0o700)
        os.chown(inbox, account.pw_uid, account.pw_gid)
        rule = (f"{args.account} ALL=(root) NOPASSWD: /usr/bin/python3 -E -s "
                "/opt/milana-erp/shared/deploy/auto_release_host.py\n")
        # Validate before making the isolated sudoers rule visible.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sudoers"
            path.write_text(rule)
            subprocess.run(["visudo", "-cf", str(path)], check=True)
            copy_atomic(path, Path("/etc/sudoers.d/milana-auto-release"), 0o440)


if __name__ == "__main__":
    main()
