"""Read-only deployment health observation; closing runtime/QA gates remain separate."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


WINDOW_SECONDS = {"low": 600, "high": 1800}
INTERVAL_SECONDS = 30
ENDPOINTS = (
    ("internal_backend", "http://172.16.10.4:8000/health", "GET"),
    ("internal_frontend", "http://172.16.10.5:3000/login", "HEAD"),
    ("public_backend", "https://erp.milanapremium.uz/health", "GET"),
    ("public_frontend", "https://erp.milanapremium.uz/login", "HEAD"),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_endpoint(url: str, method: str) -> int | str:
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(urllib.request.Request(url, method=method), timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return type(exc).__name__


def save(output: Path, evidence: dict) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


def emit_event(message: str) -> None:
    print(message, flush=True)


def observe(
    *, release: str, commit: str, output: Path, risk: str = "high", reason: str = "",
    probe=probe_endpoint, clock=time.monotonic, sleep=time.sleep, emit=emit_event,
) -> dict:
    if not re.fullmatch(r"[0-9]{8}_[0-9]{6}", release):
        raise ValueError("Release must be a UTC YYYYMMDD_HHMMSS identifier")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Commit must be the complete reviewed Git SHA")
    if risk not in WINDOW_SECONDS:
        raise ValueError("Risk must be low or high")
    if risk == "low" and not reason.strip():
        raise ValueError("Low-risk observation requires a recorded review reason")
    duration = WINDOW_SECONDS[risk]
    started = datetime.now(timezone.utc)
    evidence = {
        "release": release, "commit": commit, "risk": risk,
        "reason": reason.strip() or "Conservative default: high or uncertain risk",
        "required_seconds": duration, "interval_seconds": INTERVAL_SECONDS,
        "started_at": started.isoformat(),
        "earliest_finish_at": (started + timedelta(seconds=duration)).isoformat(),
        "status": "observing", "closing_checks_required": True,
        "checks": [], "failures": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never replace evidence from an earlier run, including an interrupted one.
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(evidence, indent=2) + "\n")
    start = clock()
    emit(json.dumps({key: evidence[key] for key in (
        "release", "risk", "status", "required_seconds", "earliest_finish_at",
    )}))
    try:
        for tick in range(duration // INTERVAL_SECONDS + 1):
            due = tick * INTERVAL_SECONDS
            # Recheck the clock if sleep returns early; never shorten the window.
            while clock() - start < due:
                sleep(max(0, due - (clock() - start)))
            elapsed = clock() - start
            if elapsed - due >= INTERVAL_SECONDS:
                evidence["failures"].append({
                    "check": "monitoring_gap", "elapsed_seconds": round(elapsed, 2),
                })
                emit(json.dumps(evidence["failures"][-1]))
                break
            row = {"elapsed_seconds": round(elapsed, 2), "at": datetime.now(timezone.utc).isoformat()}
            for name, url, method in ENDPOINTS:
                row[name] = probe(url, method)
                if row[name] != 200:
                    failure = {"check": name, "result": row[name], "at": row["at"]}
                    evidence["failures"].append(failure)
                    emit(json.dumps(failure))
            evidence["checks"].append(row)
            save(output, evidence)
        evidence["status"] = "failed" if evidence["failures"] else "health_checks_passed"
    except KeyboardInterrupt:
        evidence["status"] = "interrupted"
    except Exception:
        evidence["status"] = "observer_error"
        raise
    finally:
        evidence["elapsed_seconds"] = round(clock() - start, 2)
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(output, evidence)
        emit(json.dumps({
            "release": release, "status": evidence["status"],
            "elapsed_seconds": evidence["elapsed_seconds"],
            "failures": len(evidence["failures"]), "closing_checks_required": True,
        }))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--risk", choices=tuple(WINDOW_SECONDS), default="high")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        result = observe(**vars(args))
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    return 0 if result["status"] == "health_checks_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
