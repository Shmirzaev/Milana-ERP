import re

import pytest

from app.core.config import Settings, settings
from app.core.request_trace import (
    RequestTrace,
    _SQL_STARTED_AT_ATTRIBUTE,
    _finish_failed_sql_timing,
    bind_request_trace,
    reset_request_trace,
)


def test_local_request_trace_correlates_response_and_database_metrics(
    client,
    auth_headers,
    caplog,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOCAL_TRACE_CAPTURE_ENABLED", True)
    caplog.set_level("INFO", logger="milana.request_trace")
    secret_marker = "do-not-log-this-query-value"

    response = client.get(
        f"/api/finance/dashboard?diagnostic={secret_marker}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    request_id = response.headers.get("X-Request-ID")
    assert request_id and re.fullmatch(r"[0-9a-f]{32}", request_id)
    timing = response.headers["Server-Timing"]
    assert re.search(r"(?:^|,\s*)app;dur=\d+(?:\.\d+)?", timing)
    assert re.search(r"(?:^|,\s*)db;dur=\d+(?:\.\d+)?", timing)
    db_count = re.search(r'dbq;desc="(\d+)"', timing)
    assert db_count and int(db_count.group(1)) > 0

    records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "milana.request_trace" and "request_trace " in record.getMessage()
    ]
    matching = [record for record in records if f"request_id={request_id}" in record]
    assert len(matching) == 1
    assert "route=/api/finance/dashboard" in matching[0]
    assert f"sql_count={db_count.group(1)}" in matching[0]
    assert secret_marker not in matching[0]
    assert "authorization" not in matching[0].lower()
    assert "select " not in matching[0].lower()


def test_request_trace_is_rejected_for_production_or_public_runtime():
    configuration = Settings(ENV="production", LOCAL_TRACE_CAPTURE_ENABLED=True)

    with pytest.raises(RuntimeError, match="LOCAL_TRACE_CAPTURE_ENABLED must be false"):
        configuration.validate_runtime_security()


def test_request_trace_is_disabled_by_default():
    assert Settings().LOCAL_TRACE_CAPTURE_ENABLED is False


def test_failed_sql_execution_is_counted_without_retaining_statement():
    class ExecutionContext:
        pass

    class ExceptionContext:
        execution_context = ExecutionContext()

    context = ExceptionContext()
    setattr(context.execution_context, _SQL_STARTED_AT_ATTRIBUTE, 0.0)
    trace = RequestTrace(request_id="a" * 32)
    token = bind_request_trace(trace)
    try:
        _finish_failed_sql_timing(context)
    finally:
        reset_request_trace(token)

    assert trace.sql_count == 1
    assert trace.sql_duration_ms > 0
