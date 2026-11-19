"""Select release inputs without interpolating user-provided strings into shell code."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


def select(env, base):
    manual = env["GITHUB_EVENT_NAME"] == "workflow_dispatch" and env.get("SECURITY_ONLY") != "true"
    automatic = (env["GITHUB_EVENT_NAME"] == "push" and env["GITHUB_REF"].startswith("refs/heads/codex/")
                 and env.get("AUTO_RELEASE_BUILDS") == "true")
    if not (manual or automatic):
        return {"enabled": "false"}
    if automatic:
        run, attempt = env["GITHUB_RUN_ID"], env["GITHUB_RUN_ATTEMPT"]
        if not re.fullmatch(r"[1-9][0-9]{0,19}", run) or not re.fullmatch(r"[1-9][0-9]{0,5}", attempt):
            raise ValueError("Invalid GitHub run identity")
        release = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + f"_{run}_{attempt}"
    else:
        release = env.get("INPUT_RELEASE")
    release_base = env.get("INPUT_BASE_RELEASE") if manual else base["release"]
    manifest = env.get("INPUT_BASE_MANIFEST") if manual else base["source_manifest_sha256"]
    if not all(re.fullmatch(r"[0-9]{8}_[0-9]{6}(?:_[1-9][0-9]{0,19}_[1-9][0-9]{0,5})?", str(value or ""))
               for value in (release, release_base)):
        raise ValueError("Invalid UTC release identity")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest or "")):
        raise ValueError("Invalid baseline manifest")
    return {"enabled": "true", "release": release, "base_release": release_base, "base_manifest": manifest}


if __name__ == "__main__":
    outputs = select(os.environ, json.loads(Path("deploy/production-base.json").read_text()))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in outputs.items()))
