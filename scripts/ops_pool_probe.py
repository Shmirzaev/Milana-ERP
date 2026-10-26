"""Short bounded READ ONLY saturation of one ERP pool against the live database.

Run through stdin inside the existing backend image. No source/container edit,
business query, dependency install or application startup is required. This
measures a controlled database/pool peak, not observed factory request traffic.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import threading
import time

from sqlalchemy import create_engine, event, text

from app.core.config import settings


def main():
    if (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW) != (8, 4):
        raise RuntimeError("Live worker pool differs from reviewed 8+4 allocation")
    engine = create_engine(settings.DATABASE_URL, pool_size=8, max_overflow=4,
                           pool_timeout=2, pool_pre_ping=True,
                           connect_args={"application_name": "ops02-readonly-pool-probe",
                                         "options": "-c default_transaction_read_only=on -c statement_timeout=2000"})
    started = datetime.now(timezone.utc).isoformat()
    metrics = {"checked_out": 0, "maximum_checked_out": 0, "maximum_erp_clients": 0}
    lock = threading.Lock()

    @event.listens_for(engine, "checkout")
    def checkout(*_):
        with lock:
            metrics["checked_out"] += 1
            metrics["maximum_checked_out"] = max(metrics["maximum_checked_out"], metrics["checked_out"])

    @event.listens_for(engine, "checkin")
    def checkin(*_):
        with lock:
            metrics["checked_out"] -= 1

    try:
        with engine.connect() as connection:
            baseline = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND backend_type='client backend' AND pid<>pg_backend_pid()" )).scalar_one()
            if baseline > 32:
                raise RuntimeError("Live ERP clients leave insufficient probe and maintenance headroom")
        waits, errors, readonly = [], [], []

        def request(barrier):
            barrier.wait(timeout=5)
            before = time.perf_counter()
            try:
                with engine.connect() as connection:
                    waiting = time.perf_counter() - before
                    is_readonly = connection.execute(text("SHOW transaction_read_only")).scalar_one()
                    clients = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND backend_type='client backend'" )).scalar_one()
                    connection.execute(text("SELECT pg_sleep(0.15)"))
                    with lock:
                        waits.append(waiting * 1000)
                        readonly.append(is_readonly == "on")
                        metrics["maximum_erp_clients"] = max(metrics["maximum_erp_clients"], clients)
            except Exception as error:
                with lock:
                    errors.append(type(error).__name__)  # Never include DSNs or error values.

        with ThreadPoolExecutor(max_workers=24) as workers:
            for _ in range(8):
                barrier = threading.Barrier(24)
                futures = [workers.submit(request, barrier) for _ in range(24)]
                for future in futures:
                    future.result(timeout=10)
        waits.sort()
        passed = len(waits) == 192 and not errors and all(readonly) and metrics["maximum_checked_out"] == 12
        result = {"started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
                  "kind": "controlled read-only pool saturation; not observed factory traffic",
                  "pool_size": 8, "max_overflow": 4, "concurrent_requests": 24, "rounds": 8,
                  "existing_erp_clients": baseline, "completed": len(waits), "error_types": errors,
                  "all_transactions_read_only": all(readonly), **metrics,
                  "checkout_wait_ms": {"p50": waits[len(waits)//2] if waits else None,
                                       "p95": waits[int(len(waits)*0.95)] if waits else None,
                                       "maximum": max(waits) if waits else None},
                  "passed": passed}
        print(json.dumps(result))
        if not passed:
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
