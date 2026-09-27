import copy
import json
import socket
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient
import pytest

from scripts.report_api_test_coverage import (
    CoveragePlugin, ObservedApp, TrafficLedger, configure_test_environment, loopback_sockets_only,
    merge_reports, route_inventory,
)


def sample_app():
    app = FastAPI()

    @app.get("/accounts/{account_id}")
    def account(account_id: int):
        if account_id == 2:
            raise HTTPException(403, "private rejection body")
        return {"private": "RESPONSE_SECRET"}

    @app.post("/accounts/{account_id}", status_code=201)
    def create_account(account_id: int):
        return {"private": "POST_SECRET"}

    @app.put("/unhit")
    def unhit():
        return {}

    return app


def row(report, method, path):
    return next(value for value in report["routes"] if (value["method"], value["path"]) == (method, path))


def test_inventory_is_method_specific_and_excludes_automatic_docs():
    app = sample_app()
    assert {(method, path) for method, path, _ in route_inventory(app)} == {
        ("GET", "/accounts/{account_id}"), ("POST", "/accounts/{account_id}"), ("PUT", "/unhit"),
    }


def test_statuses_use_patterns_without_payloads_credentials_or_concrete_ids():
    app = sample_app()
    ledger = TrafficLedger(app)
    client = TestClient(ObservedApp(app, ledger))
    assert client.get("/accounts/719382?token=QUERY_SECRET", headers={"Authorization": "Bearer HEADER_SECRET"}).status_code == 200
    assert client.get("/accounts/2").status_code == 403
    assert client.get("/accounts/INVALID_USER_ID").status_code == 422
    assert client.post("/accounts/719382", json={"password": "BODY_SECRET"}).status_code == 201
    report = ledger.report()
    assert row(report, "GET", "/accounts/{account_id}")["statuses"] == {"200": 1, "403": 1, "422": 1}
    assert row(report, "GET", "/accounts/{account_id}")["categories"] == ["success", "rejection"]
    assert row(report, "PUT", "/unhit")["categories"] == ["unhit"]
    assert report["summary"]["endpoints"] == 3
    assert report["summary"]["observed"] == 2
    encoded = json.dumps(report)
    for secret in ("719382", "INVALID_USER_ID", "QUERY_SECRET", "HEADER_SECRET", "BODY_SECRET", "RESPONSE_SECRET", "POST_SECRET"):
        assert secret not in encoded


def test_unknown_paths_and_wrong_methods_are_not_credited_to_an_endpoint():
    app = sample_app()
    ledger = TrafficLedger(app)
    client = TestClient(ObservedApp(app, ledger))
    assert client.get("/unknown/PRIVATE_ID").status_code == 404
    assert client.delete("/accounts/PRIVATE_ID").status_code == 405
    report = ledger.report()
    assert report["summary"]["observed"] == 0
    assert report["summary"]["requests"] == 2
    assert report["unattributed"]["statuses"] == {"404": 1, "405": 1}
    assert "PRIVATE_ID" not in json.dumps(report)


def test_middleware_rejections_are_attributed_but_not_claimed_as_dispatch():
    app = sample_app()

    @app.middleware("http")
    async def reject_early(request, call_next):
        return Response(status_code=401)

    ledger = TrafficLedger(app)
    assert TestClient(ObservedApp(app, ledger)).get("/accounts/1").status_code == 401
    observed = row(ledger.report(), "GET", "/accounts/{account_id}")
    assert observed["before_dispatch"] == 1
    assert observed["dispatched"] == 0
    assert observed["categories"] == ["rejection"]


def test_mounted_fastapi_route_uses_full_parent_pattern():
    app = FastAPI()
    child = sample_app()
    app.mount("/nested", child)
    ledger = TrafficLedger(app)
    assert TestClient(ObservedApp(app, ledger)).get("/nested/accounts/123").status_code == 200
    observed = row(ledger.report(), "GET", "/nested/accounts/{account_id}")
    assert observed["statuses"] == {"200": 1}
    assert observed["dispatched"] == 1


def test_raised_exceptions_are_preserved_without_recording_exception_text():
    app = FastAPI()

    @app.get("/broken/{private_id}")
    def broken(private_id: str):
        raise RuntimeError("EXCEPTION_SECRET")

    ledger = TrafficLedger(app)
    with pytest.raises(RuntimeError, match="EXCEPTION_SECRET"):
        TestClient(ObservedApp(app, ledger)).get("/broken/CONCRETE_SECRET")
    observed = row(ledger.report(), "GET", "/broken/{private_id}")
    assert observed["statuses"] == {"500": 1}
    assert observed["exceptions"] == 1
    assert "EXCEPTION_SECRET" not in json.dumps(ledger.report())
    assert "CONCRETE_SECRET" not in json.dumps(ledger.report())


def test_redirect_does_not_turn_its_unrouted_request_into_a_success():
    app = FastAPI()

    @app.get("/slash/")
    def slash():
        return {}

    ledger = TrafficLedger(app)
    assert TestClient(ObservedApp(app, ledger)).get("/slash").status_code == 200
    report = ledger.report()
    assert row(report, "GET", "/slash/")["statuses"] == {"200": 1}
    assert report["unattributed"]["statuses"] == {"307": 1}


def test_merge_deduplicates_runs_and_combines_distinct_batches():
    app = sample_app()
    first, second = TrafficLedger(app), TrafficLedger(app)
    TestClient(ObservedApp(app, first)).get("/accounts/1")
    TestClient(ObservedApp(app, second)).get("/accounts/2")
    first_report, second_report = first.report(), second.report(pytest_exit_code=1, test_outcomes={"failed": 1})
    merged = merge_reports([first_report, second_report, first_report])
    assert merged["summary"]["runs"] == 2
    assert merged["summary"]["failed_runs"] == 1
    assert merged["summary"]["requests"] == 2
    assert row(merged, "GET", "/accounts/{account_id}")["statuses"] == {"200": 1, "403": 1}
    assert merged["runs"][1]["pytest_exit_code"] == 1
    assert merge_reports([merged, first_report]) == merged


def test_merge_rejects_different_inventories_and_conflicting_run_data():
    first = TrafficLedger(sample_app()).report()
    with pytest.raises(ValueError, match="inventories"):
        merge_reports([first, TrafficLedger(FastAPI()).report()])
    changed = copy.deepcopy(first)
    changed["runs"][0]["pytest_exit_code"] = 1
    with pytest.raises(ValueError, match="Conflicting"):
        merge_reports([first, changed])


def test_merge_preserves_revision_and_dirty_markers_for_each_run():
    first = TrafficLedger(sample_app()).report(source_revision="a" * 40, source_dirty=False)
    second = TrafficLedger(sample_app()).report(source_revision="b" * 40, source_dirty=True)
    merged = merge_reports([first, second])
    assert merged["summary"]["source_revisions"] == ["a" * 40, "b" * 40]
    assert merged["summary"]["dirty_runs"] == 1
    assert [run["source_dirty"] for run in merged["runs"]] == [False, True]


def test_test_environment_removes_unrelated_network_and_monitor_settings():
    environment = {
        "AI_MONITOR_PASSWORD": "PRIVATE", "SMTP_USERNAME": "PRIVATE", "HTTPS_PROXY": "PRIVATE",
        "STABILIZATION_POSTGRES_URL": "PRIVATE", "DATABASE_URL": "PRIVATE", "PATH": "keep",
    }
    configure_test_environment(environment)
    assert "PRIVATE" not in repr(environment)
    assert environment["AI_MONITOR_PASSWORD"] == ""
    assert environment["DATABASE_URL"] == "sqlite:///:memory:"
    assert environment["PATH"] == "keep"


def test_loopback_guard_blocks_network_before_resolution_or_connect(monkeypatch):
    connected = []
    monkeypatch.setattr(socket.socket, "connect", lambda sock, address: connected.append(address))
    with loopback_sockets_only(), socket.socket() as sock:
        with pytest.raises(RuntimeError, match="Non-loopback"):
            socket.getaddrinfo("outside.invalid", 443)
        with pytest.raises(RuntimeError, match="Non-loopback"):
            sock.connect(("203.0.113.20", 443))
        sock.connect(("127.0.0.1", 12345))
    assert connected == [("127.0.0.1", 12345)]


def test_merge_does_not_copy_arbitrary_metadata_into_the_ledger():
    report = TrafficLedger(sample_app()).report()
    report["request_body"] = "PRIVATE_BODY"
    report["runs"][0]["headers"] = {"Authorization": "PRIVATE_TOKEN"}
    merged = merge_reports([report])
    assert "PRIVATE" not in json.dumps(merged)


def test_report_snapshot_is_not_changed_by_later_requests():
    app = sample_app()
    ledger = TrafficLedger(app)
    before = ledger.report()
    TestClient(ObservedApp(app, ledger)).get("/accounts/1")
    assert before["summary"]["requests"] == 0
    assert ledger.report()["summary"]["requests"] == 1


def test_teardown_failure_overrides_pass_without_retaining_the_test_identity():
    plugin = CoveragePlugin()
    for when, outcome in (("call", "passed"), ("teardown", "failed")):
        plugin.pytest_runtest_logreport(SimpleNamespace(
            nodeid="test[PRIVATE_ACTOR_ID]", when=when, outcome=outcome,
            failed=outcome == "failed", skipped=False,
        ))
    assert list(plugin.outcomes.values()) == ["failed"]
    assert "PRIVATE_ACTOR_ID" not in repr(plugin.outcomes)


def test_real_application_request_is_observed_by_the_optional_runner(client):
    # Deliberately touches one real route in the conftest's synthetic application.
    # The helper's custom miniature apps must not pollute the application's ledger.
    assert client.get("/api/auth/me").status_code == 401
