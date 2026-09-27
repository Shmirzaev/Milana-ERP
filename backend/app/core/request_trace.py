"""Opt-in, data-minimizing request/SQL timing correlation for local QA."""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from time import perf_counter

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass(slots=True)
class RequestTrace:
    request_id: str
    sql_count: int = 0
    sql_duration_ms: float = 0.0


_current_trace: ContextVar[RequestTrace | None] = ContextVar("ops01_request_trace", default=None)
_SQL_STARTED_AT_ATTRIBUTE = "_milana_ops01_sql_started_at"
_listeners_installed = False
_listener_install_lock = Lock()


def bind_request_trace(trace: RequestTrace) -> Token[RequestTrace | None]:
    return _current_trace.set(trace)


def reset_request_trace(token: Token[RequestTrace | None]) -> None:
    _current_trace.reset(token)


def install_sql_timing_listeners() -> None:
    """Install SQL hooks only when a local trace is explicitly enabled."""
    global _listeners_installed
    if _listeners_installed:
        return
    with _listener_install_lock:
        if _listeners_installed:
            return
        event.listen(Engine, "before_cursor_execute", _start_sql_timing)
        event.listen(Engine, "after_cursor_execute", _finish_sql_timing)
        event.listen(Engine, "handle_error", _finish_failed_sql_timing)
        _listeners_installed = True


def _start_sql_timing(_connection, _cursor, _statement, _parameters, context, _executemany):
    if _current_trace.get() is None or context is None:
        return
    setattr(context, _SQL_STARTED_AT_ATTRIBUTE, perf_counter())


def _finish_sql_timing(_connection, _cursor, _statement, _parameters, context, _executemany):
    trace = _current_trace.get()
    if trace is None or context is None:
        return
    started_at = getattr(context, _SQL_STARTED_AT_ATTRIBUTE, None)
    if started_at is None:
        return
    trace.sql_count += 1
    trace.sql_duration_ms += (perf_counter() - started_at) * 1000
    delattr(context, _SQL_STARTED_AT_ATTRIBUTE)


def _finish_failed_sql_timing(exception_context):
    context = exception_context.execution_context
    trace = _current_trace.get()
    if trace is None or context is None:
        return
    started_at = getattr(context, _SQL_STARTED_AT_ATTRIBUTE, None)
    if started_at is None:
        return
    trace.sql_count += 1
    trace.sql_duration_ms += (perf_counter() - started_at) * 1000
    delattr(context, _SQL_STARTED_AT_ATTRIBUTE)
