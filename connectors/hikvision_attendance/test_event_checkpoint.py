"""Event-window completion and retry regressions; all HTTP uses MockTransport."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

import read_only_connector as connector


NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def event(serial: int) -> dict:
    return {
        "serialNo": serial,
        "employeeNoString": "synthetic-employee",
        "time": (NOW - timedelta(hours=1)).isoformat(),
        "attendanceStatus": "checkIn",
    }


def page(events: list[dict], total: int, **extra) -> dict:
    return {"AcsEvent": {
        "InfoList": events,
        "numOfMatches": len(events),
        "totalMatches": total,
        **extra,
    }}


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.astimezone().replace(tzinfo=None)

    monkeypatch.setattr(connector, "datetime", FrozenDatetime)
    monkeypatch.setattr(connector.time, "sleep", lambda _: None)

    def blocked_network(*args, **kwargs):
        raise AssertionError("Live network is forbidden in connector regressions")

    monkeypatch.setattr(connector.socket, "create_connection", blocked_network)
    monkeypatch.setattr(connector.ReadOnlyHikvision, "_urllib_request", blocked_network)
    config = connector.Config(
        hikvision_base_url="https://device.example.test",
        hikvision_username="synthetic",
        hikvision_password="unused",
        hikvision_cert_sha256="0" * 64,
        erp_base_url="https://erp.example.test",
        erp_token="unused",
        page_size=2,
        state_path=str(tmp_path / "state.json"),
    )
    scenario = SimpleNamespace(
        config=config,
        state={"version": 1, "last_event_cursor": (NOW - timedelta(hours=12)).isoformat()},
        pages=[], searches=[], uploads=[], stored=set(), fail_upload=None,
    )

    def device_http(request):
        if request.url.path == "/ISAPI/System/deviceInfo":
            return httpx.Response(200, json={"DeviceInfo": {"model": "synthetic"}})
        if request.url.path == "/ISAPI/AccessControl/UserInfo/Count":
            return httpx.Response(200, json={"UserInfoCount": {"userNumber": 1}})
        assert request.method == "POST"
        assert request.url.path == "/ISAPI/AccessControl/AcsEvent"
        scenario.searches.append(json.loads(request.content)["AcsEventCond"])
        response = scenario.pages.pop(0)
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    def erp_http(request):
        assert request.method == "POST"
        assert request.url.path == "/api/attendance/integration/events"
        assert request.headers["X-Attendance-Token"] == "unused"
        events = json.loads(request.content)["events"]
        scenario.uploads.append(events)
        if scenario.fail_upload == len(scenario.uploads):
            return httpx.Response(503)
        inserted = sum(item["event_uid"] not in scenario.stored for item in events)
        scenario.stored.update(item["event_uid"] for item in events)
        return httpx.Response(200, json={
            "received": len(events), "inserted": inserted, "duplicates": len(events) - inserted,
        })

    real_client = httpx.Client

    def mock_client(**kwargs):
        handler = device_http if kwargs["base_url"] == config.hikvision_base_url else erp_http
        return real_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(connector.httpx, "Client", mock_client)
    scenario.hik = connector.ReadOnlyHikvision(config)
    scenario.erp = connector.ErpMirror(config)
    connector.save_state(connector.Path(config.state_path), scenario.state)
    try:
        yield scenario
    finally:
        scenario.hik.close()
        scenario.erp.close()


def sync(scenario):
    connector.sync_events(scenario.config, scenario.hik, scenario.erp, scenario.state)


def assert_cursor(scenario, expected):
    assert scenario.state["last_event_cursor"] == expected
    assert connector.load_state(connector.Path(scenario.config.state_path))["last_event_cursor"] == expected


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_complete_event_window_is_uploaded_and_checkpointed(scenario, count):
    records = [event(serial) for serial in range(count)]
    scenario.pages = [page(records[i:i + 2], count) for i in range(0, count, 2)] or [page([], 0)]

    sync(scenario)

    assert len(scenario.stored) == count
    assert_cursor(scenario, NOW.isoformat())
    assert [request["searchResultPosition"] for request in scenario.searches] == (list(range(0, count, 2)) or [0])
    assert len({request["searchID"] for request in scenario.searches}) == 1
    assert not scenario.pages


@pytest.mark.parametrize("last_page", [
    page([], 3),
    page([event(2)], 3, numOfMatches=2),
    page([], 0),
    page([event(2)], 4),
    page([event(2)], 3, responseStatusStrg="MORE"),
    page([event(2)], 3, responseStatusStrg="FAILED"),
    page([], 3, responseStatusStrg="NO MATCH"),
    {"AcsEvent": {"InfoList": [], "numOfMatches": 0, "responseStatusStrg": "MORE"}},
    {"ResponseStatus": {"statusCode": 4, "statusString": "Invalid Operation"}},
    {"AcsEvent": {}},
], ids=[
    "early-empty", "truncated-page", "shrinking-total", "growing-total", "more-at-total",
    "failed-status", "premature-no-match", "empty-more", "device-error", "missing-result",
])
def test_incomplete_event_window_never_uploads_or_advances_cursor(scenario, last_page):
    saved = scenario.state["last_event_cursor"]
    scenario.pages = [page([event(0), event(1)], 3), last_page]

    with pytest.raises(RuntimeError):
        sync(scenario)

    assert_cursor(scenario, saved)
    assert not scenario.uploads


def test_status_more_without_total_fetches_remaining_events(scenario):
    scenario.pages = [
        {"AcsEvent": {"InfoList": [event(0), event(1)], "numOfMatches": 2, "responseStatusStrg": "MORE"}},
        {"AcsEvent": {"InfoList": [event(2)], "numOfMatches": 1, "responseStatusStrg": "OK"}},
    ]

    sync(scenario)

    assert len(scenario.stored) == 3
    assert [request["searchResultPosition"] for request in scenario.searches] == [0, 2]
    assert_cursor(scenario, NOW.isoformat())


def test_missing_completion_evidence_does_not_advance_cursor(scenario):
    saved = scenario.state["last_event_cursor"]
    scenario.pages = [{"AcsEvent": {"InfoList": [event(0)], "numOfMatches": 1}}]

    with pytest.raises(RuntimeError):
        sync(scenario)

    assert_cursor(scenario, saved)
    assert not scenario.uploads


@pytest.mark.parametrize("firmware_response", [
    {"AcsEventSearchResult": {"infoList": {"acsEventInfo": event(0)}, "numOfMatches": "1", "totalMatches": "1"}},
    httpx.Response(200, content=b"""<AcsEvent>
      <InfoList><AcsEventInfo><serialNo>0</serialNo><employeeNoString>synthetic-employee</employeeNoString>
      <time>2026-09-18T11:00:00+00:00</time><attendanceStatus>checkIn</attendanceStatus></AcsEventInfo></InfoList>
      <numOfMatches>1</numOfMatches><totalMatches>1</totalMatches>
    </AcsEvent>"""),
], ids=["alternate-json-shape", "xml-nested-single-event"])
def test_complete_firmware_response_variants_remain_supported(scenario, firmware_response):
    scenario.pages = [firmware_response]

    sync(scenario)

    assert len(scenario.stored) == 1
    assert_cursor(scenario, NOW.isoformat())


@pytest.mark.parametrize("empty_result", [
    {"AcsEvent": {"numOfMatches": 0, "responseStatusStrg": "NO MATCH"}},
    {"AcsEvent": {"InfoList": {"AcsEventInfo": []}, "numOfMatches": 0, "totalMatches": 0}},
], ids=["no-match-status", "empty-nested-list"])
def test_explicit_empty_window_can_be_checkpointed(scenario, empty_result):
    scenario.pages = [empty_result]

    sync(scenario)

    assert scenario.uploads == [[]]
    assert_cursor(scenario, NOW.isoformat())


@pytest.mark.parametrize("failure", ["http", "truncated"])
def test_partial_fetch_preserves_cursor_and_retry_restarts_window(scenario, failure):
    saved = scenario.state["last_event_cursor"]
    tail = [httpx.Response(503) for _ in range(3)] if failure == "http" else [page([], 3)]
    scenario.pages = [page([event(0), event(1)], 3)] + tail

    with pytest.raises(httpx.HTTPStatusError if failure == "http" else RuntimeError):
        sync(scenario)

    assert_cursor(scenario, saved)
    assert not scenario.uploads
    assert [request["searchResultPosition"] for request in scenario.searches] == [0] + [2] * len(tail)
    first_search = scenario.searches[0]
    retry_index = len(scenario.searches)
    scenario.pages = [page([event(0), event(1)], 3), page([event(2)], 3)]
    sync(scenario)

    assert scenario.searches[retry_index]["startTime"] == first_search["startTime"]
    assert scenario.searches[retry_index]["searchResultPosition"] == 0
    assert scenario.searches[retry_index]["searchID"] != first_search["searchID"]
    assert len(scenario.stored) == 3
    assert_cursor(scenario, NOW.isoformat())


def test_failed_upload_batch_retries_complete_window_with_stable_event_ids(scenario):
    saved = scenario.state["last_event_cursor"]
    records = [event(serial) for serial in range(1001)]
    scenario.config.page_size = 100
    scenario.pages = [page(records[i:i + 100], len(records)) for i in range(0, len(records), 100)]
    retry_pages = list(scenario.pages)
    scenario.fail_upload = 2

    with pytest.raises(httpx.HTTPStatusError):
        sync(scenario)

    assert_cursor(scenario, saved)
    assert len(scenario.stored) == 1000
    scenario.pages = retry_pages
    sync(scenario)

    assert scenario.uploads[0] == scenario.uploads[2]
    assert len(scenario.stored) == 1001
    assert_cursor(scenario, NOW.isoformat())


def test_completed_day_checkpoint_survives_partial_next_day(scenario):
    scenario.state["last_event_cursor"] = (NOW - timedelta(days=2) + timedelta(minutes=5)).isoformat()
    scenario.pages = [page([event(0)], 1), page([event(1)], 2), page([], 2)]

    with pytest.raises(RuntimeError):
        sync(scenario)

    assert len(scenario.stored) == 1
    assert_cursor(scenario, (NOW - timedelta(days=1)).isoformat())
