from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def npm_cmd() -> str:
    resolved = shutil.which("npm")
    if not resolved:
        raise RuntimeError("npm was not found on PATH")
    return resolved


def run(name: str, cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n=== {name} ===", flush=True)
    print("$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Milana ERP quality and security checks.")
    parser.add_argument("--skip-build", action="store_true", help="Skip the frontend production build.")
    args = parser.parse_args()

    run("python compile", [sys.executable, "-m", "compileall", "-q", "backend/app"])
    run("backend tests", [sys.executable, "-m", "pytest", "-q"], ROOT / "backend")
    run("backend security scan", [sys.executable, "-m", "bandit", "-r", "app", "-x", "app/tests", "-q"], ROOT / "backend")
    run("backend critical lint", [sys.executable, "-m", "ruff", "check", "app"], ROOT / "backend")
    run("backend dependency audit", [sys.executable, "-m", "pip_audit", "-r", "requirements.txt"], ROOT / "backend")
    run("frontend dependency audit", [npm_cmd(), "audit", "--omit=dev"], ROOT / "frontend")
    run("frontend lint", [npm_cmd(), "run", "lint"], ROOT / "frontend")
    run("frontend typecheck", [npm_cmd(), "exec", "tsc", "--", "--noEmit"], ROOT / "frontend")
    if not args.skip_build:
        run("frontend build", [npm_cmd(), "run", "build"], ROOT / "frontend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
