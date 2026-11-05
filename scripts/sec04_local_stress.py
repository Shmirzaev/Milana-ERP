"""Bounded SEC04 HTTP load against the disposable loopback stack only."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookies import SimpleCookie
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sec04_local_stack import BACKEND_URL, ROOT, pg_connections, read_state, fixture


# Reviewed limits belong in docs/qa/SEC04_LOCAL_VERIFICATION.md before execution.
CONCURRENCY = 8
REQUESTS_PER_PHASE = 80
REQUEST_TIMEOUT_SECONDS = 5
MAX_RUN_SECONDS = 45
P95_LIMIT_MS = 2500
P99_LIMIT_MS = 4000
MAX_POSTGRES_CONNECTIONS = 20
FILE = "/storage/model-files/sec04-verification.png"
THUMB = "/storage/model-files/thumb/sec04-verification.png?size=160"


def login(email: str, password: str) -> str:
    data = json.dumps({"email": email, "password": password, "factory_code": "MIL"}).encode()
    request = Request(BACKEND_URL + "/api/auth/login-json", data=data,
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise AssertionError(f"login returned {response.status}")
        cookies = SimpleCookie()
        cookies.load(response.headers.get("Set-Cookie", ""))
    return f"erp_access_token={cookies['erp_access_token'].value}"


def get(path: str, cookie: str) -> tuple[int, float, str]:
    started = time.perf_counter()
    try:
        with urlopen(Request(BACKEND_URL + path, headers={"Cookie": cookie}),
                     timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
            status = response.status
    except HTTPError as exc:
        exc.read()
        status = exc.code
    except (URLError, TimeoutError):
        status = 0
    return status, (time.perf_counter() - started) * 1000, path.split("?")[0]


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, int((len(ordered) * percent + 99) // 100) - 1)], 1)


def wave(name: str, cookie: str, expected: int) -> dict:
    samples: list[int] = []
    stop = threading.Event()

    def sample_connections() -> None:
        while not stop.is_set():
            samples.append(pg_connections())
            stop.wait(0.01)

    monitor = threading.Thread(target=sample_connections, daemon=True)
    started = time.perf_counter()
    monitor.start()
    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [pool.submit(get, FILE if index % 2 == 0 else THUMB, cookie)
                       for index in range(REQUESTS_PER_PHASE)]
            results = [future.result() for future in as_completed(futures)]
    finally:
        stop.set()
        monitor.join(timeout=REQUEST_TIMEOUT_SECONDS)
    elapsed = time.perf_counter() - started
    latencies = [duration for _, duration, _ in results]
    statuses = {status: sum(row[0] == status for row in results)
                for status in sorted({row[0] for row in results})}
    outcome = {"phase": name, "expected_status": expected, "statuses": statuses,
               "requests": len(results), "seconds": round(elapsed, 2),
               "requests_per_second": round(len(results) / elapsed, 1),
               "p50_ms": percentile(latencies, 50), "p95_ms": percentile(latencies, 95),
               "p99_ms": percentile(latencies, 99), "max_ms": round(max(latencies), 1),
               "max_postgres_connections": max(samples) if samples else None}
    if statuses != {expected: REQUESTS_PER_PHASE}:
        raise AssertionError(f"{name}: unexpected statuses {statuses}")
    if outcome["p95_ms"] > P95_LIMIT_MS or outcome["p99_ms"] > P99_LIMIT_MS:
        raise AssertionError(f"{name}: latency exceeded recorded limits: {outcome}")
    if outcome["max_postgres_connections"] is None or outcome["max_postgres_connections"] > MAX_POSTGRES_CONNECTIONS:
        raise AssertionError(f"{name}: PostgreSQL connection limit exceeded or unmeasured: {outcome}")
    return outcome


def main() -> None:
    state = read_state()
    if not BACKEND_URL.startswith("http://127.0.0.1:"):
        raise RuntimeError("SEC04 stress target must be loopback")
    limits = {"concurrency": CONCURRENCY, "requests_per_phase": REQUESTS_PER_PHASE,
              "phases": ["active", "revoked", "recovery"],
              "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
              "max_run_seconds": MAX_RUN_SECONDS, "p95_limit_ms": P95_LIMIT_MS,
              "p99_limit_ms": P99_LIMIT_MS, "unexpected_5xx_limit": 0,
              "post_revocation_200_limit": 0,
              "max_postgres_connections": MAX_POSTGRES_CONNECTIONS,
              "fixture_dimensions_px": [160, 160]}
    print("Recorded limits:", json.dumps(limits), flush=True)
    started = time.perf_counter()
    viewer = login("sec04-viewer@example.com", os.environ["SEC04_VIEWER_PASSWORD"])
    assert get(FILE, viewer)[0] == get(THUMB, viewer)[0] == 200
    baseline_connections = pg_connections()
    active = wave("active", viewer, 200)
    fixture("revoke")
    revoked = wave("revoked", viewer, 401)
    admin = login("sec04-admin@example.com", os.environ["SEC04_ADMIN_PASSWORD"])
    recovery = wave("recovery", admin, 200)
    with urlopen(BACKEND_URL + "/ready", timeout=REQUEST_TIMEOUT_SECONDS) as response:
        assert response.status == 200
    from subprocess import check_output
    import sys
    readback = json.loads(check_output([sys.executable, str(ROOT / "scripts/sec04_local_stack.py"),
                                        "readback"], text=True))
    assert readback["is_active"] is False
    assert readback["image_records"] == 1 and readback["file_exists"] is True
    elapsed = time.perf_counter() - started
    assert elapsed <= MAX_RUN_SECONDS, f"run exceeded {MAX_RUN_SECONDS}s: {elapsed:.1f}s"
    result = {"candidate_commit": state["commit"], "stack_project": state["project"],
              "limits": limits, "elapsed_seconds": round(elapsed, 2),
              "baseline_postgres_connections": baseline_connections,
              "phases": [active, revoked, recovery], "readback": readback,
              "ready_after_load": True}
    output = ROOT / "outputs/sec04-verification/stress.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
