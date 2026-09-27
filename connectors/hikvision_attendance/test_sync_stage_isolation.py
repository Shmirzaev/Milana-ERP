"""Roster outages must not suppress independently readable attendance events."""

from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest

import read_only_connector as connector
from test_event_checkpoint import NOW, assert_cursor, event, page, scenario  # noqa: F401


@pytest.fixture
def run_case(scenario, monkeypatch):
    monkeypatch.setattr(scenario.config, "validate", Mock())
    monkeypatch.setattr(connector, "ReadOnlyHikvision", lambda _: scenario.hik)
    monkeypatch.setattr(connector, "ErpMirror", lambda _: scenario.erp)
    scenario.real_people_sync = connector.sync_people
    scenario.people_sync = Mock(side_effect=RuntimeError("roster unavailable"))
    monkeypatch.setattr(connector, "sync_people", scenario.people_sync)
    scenario.pages = [page([event(1)], 1)]
    return scenario


@pytest.mark.parametrize("mode", ["all", "scheduled"])
def test_roster_failure_still_uploads_events_and_reports_failure(run_case, mode):
    case = run_case
    with pytest.raises(RuntimeError, match="roster unavailable"):
        connector.run_sync(case.config, mode)

    assert len(case.stored) == 1
    assert connector.load_state(connector.Path(case.config.state_path))["last_event_cursor"] == NOW.isoformat()
    assert "last_people_sync_at" not in connector.load_state(connector.Path(case.config.state_path))
    assert case.people_sync.call_count == 1
    assert case.hik.client.is_closed and case.erp.client.is_closed


def test_both_failures_are_reported_without_advancing_event_cursor(run_case):
    case = run_case
    saved = case.state["last_event_cursor"]
    case.pages = [httpx.Response(503)] * 3
    with pytest.raises(RuntimeError) as caught:
        connector.run_sync(case.config, "scheduled")
    assert "People sync failed" in str(caught.value)
    assert "Event sync failed" in str(caught.value)
    assert not case.stored
    assert_cursor(case, saved)
    assert case.hik.client.is_closed and case.erp.client.is_closed


@pytest.mark.parametrize("mode", ["people", "events", "all", "scheduled"])
def test_mode_success_preserves_selected_stages(run_case, mode):
    case = run_case
    case.people_sync.side_effect = None
    connector.run_sync(case.config, mode)
    assert case.people_sync.call_count == int(mode != "events")
    assert len(case.stored) == int(mode != "people")
    assert case.hik.client.is_closed and case.erp.client.is_closed


def test_recent_roster_is_not_retried_during_scheduled_event_sync(run_case):
    case = run_case
    case.state["last_people_sync_at"] = (NOW - timedelta(minutes=1)).isoformat()
    connector.save_state(connector.Path(case.config.state_path), case.state)
    connector.run_sync(case.config, "scheduled")
    assert not case.people_sync.called
    assert len(case.stored) == 1


def test_people_only_failure_never_downloads_events(run_case):
    case = run_case
    with pytest.raises(RuntimeError, match="roster unavailable"):
        connector.run_sync(case.config, "people")
    assert case.people_sync.called and not case.searches and not case.uploads
    assert case.hik.client.is_closed and case.erp.client.is_closed


def test_certificate_failure_never_creates_clients_or_starts_stages(run_case, monkeypatch):
    case = run_case
    case.config.validate.side_effect = RuntimeError("TLS identity changed")
    clients = Mock(side_effect=AssertionError("Must not create a client"))
    monkeypatch.setattr(connector, "ReadOnlyHikvision", clients)
    with pytest.raises(RuntimeError, match="TLS identity changed"):
        connector.run_sync(case.config, "all")
    assert not clients.called and not case.people_sync.called and not case.uploads


def test_optional_roster_count_failure_does_not_block_events(run_case, monkeypatch):
    case = run_case
    case.people_sync.side_effect = None
    monkeypatch.setattr(case.hik, "person_count", Mock(side_effect=RuntimeError("count unavailable")))
    device_payloads = []
    original = case.erp.events

    def capture(device, events, *, source_snapshot_at):
        device_payloads.append(device)
        return original(device, events, source_snapshot_at=source_snapshot_at)

    monkeypatch.setattr(case.erp, "events", capture)
    connector.run_sync(case.config, "events")
    assert len(case.stored) == 1
    assert device_payloads[0]["reported_person_count"] is None  # Unknown, not a false zero.


def test_real_incomplete_roster_does_not_upload_snapshot_but_events_continue(run_case, monkeypatch):
    case = run_case
    monkeypatch.setattr(connector, "sync_people", case.real_people_sync)
    monkeypatch.setattr(case.hik, "people", lambda: [])  # Count endpoint advertises one.
    people_upload = Mock(side_effect=AssertionError("Incomplete roster must not upload"))
    monkeypatch.setattr(case.erp, "people", people_upload)
    with pytest.raises(RuntimeError, match="Device reported 1 people but search returned 0"):
        connector.run_sync(case.config, "scheduled")
    assert not people_upload.called and len(case.stored) == 1
    saved = connector.load_state(connector.Path(case.config.state_path))
    assert saved["last_event_cursor"] == NOW.isoformat() and "last_people_sync_at" not in saved


def test_keyboard_interrupt_is_not_swallowed(run_case):
    case = run_case
    case.people_sync.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        connector.run_sync(case.config, "all")
    assert not case.searches
    assert case.hik.client.is_closed and case.erp.client.is_closed
