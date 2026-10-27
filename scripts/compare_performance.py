"""Fail a release when its warmed read-only benchmark regresses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict[str, dict[str, float | int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"Invalid performance evidence: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--median-budget", type=float, default=0.10)
    parser.add_argument("--p95-budget", type=float, default=0.15)
    parser.add_argument("--payload-budget", type=float, default=0.15)
    args = parser.parse_args()
    baseline = load(args.baseline)
    candidate = load(args.candidate)
    failures: list[str] = []
    report: dict[str, dict[str, float | int]] = {}

    for name, before in baseline.items():
        after = candidate.get(name)
        if after is None:
            failures.append(f"{name}: missing from candidate evidence")
            continue
        if int(after["rows"]) != int(before["rows"]):
            failures.append(f"{name}: row count changed {before['rows']} -> {after['rows']}")
        median_ratio = float(after["median_ms"]) / max(float(before["median_ms"]), 0.01)
        p95_ratio = float(after["p95_ms"]) / max(float(before["p95_ms"]), 0.01)
        payload_ratio = float(after["response_bytes"]) / max(float(before["response_bytes"]), 1.0)
        report[name] = {
            "baseline_median_ms": float(before["median_ms"]),
            "candidate_median_ms": float(after["median_ms"]),
            "median_change_pct": round((median_ratio - 1) * 100, 2),
            "p95_change_pct": round((p95_ratio - 1) * 100, 2),
            "payload_change_pct": round((payload_ratio - 1) * 100, 2),
        }
        if median_ratio > 1 + args.median_budget:
            failures.append(f"{name}: median regressed {(median_ratio - 1) * 100:.1f}%")
        if p95_ratio > 1 + args.p95_budget:
            failures.append(f"{name}: p95 regressed {(p95_ratio - 1) * 100:.1f}%")
        if payload_ratio > 1 + args.payload_budget:
            failures.append(f"{name}: payload grew {(payload_ratio - 1) * 100:.1f}%")

    print(json.dumps({"report": report, "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
