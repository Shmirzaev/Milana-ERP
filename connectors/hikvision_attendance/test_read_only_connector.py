from __future__ import annotations

import pytest
import httpx

from read_only_connector import (
    Config,
    ReadOnlyHikvision,
    normalize_event,
    normalize_person,
    response_json,
    sync_events,
)


def config() -> Config:
    return Config(
        hikvision_base_url="https://10.100.50.41",
        hikvision_username="admin",
        hikvision_password="unused",
        hikvision_cert_sha256="0" * 64,
        erp_base_url="https://erp.example.test",
        erp_token="unused",
    )


def test_hikvision_transport_blocks_non_search_posts():
    client = ReadOnlyHikvision(config())
    try:
        with pytest.raises(RuntimeError, match="Blocked non-read-only"):
            client.post_search("/ISAPI/AccessControl/UserInfo/Record?format=json", {"UserInfo": {}})
    finally:
        client.close()


def test_profile_and_event_normalization():
    profile, photo = normalize_person({
        "employeeNo": "735",
        "name": "Example Person",
        "userType": "normal",
        "numOfFace": 1,
        "numOfCard": 2,
        "Valid": {"enable": True, "beginTime": "2025-01-01T00:00:00+05:00"},
        "faceURL": "/ISAPI/example/picture",
    })
    assert profile["external_person_id"] == "735"
    assert profile["has_face"] is True
    assert photo == "/ISAPI/example/picture"

    event = normalize_event({
        "serialNo": 10,
        "employeeNoString": "735",
        "time": "2026-08-17T08:15:00+05:00",
        "attendanceStatus": "checkIn",
        "currentVerifyMode": "face",
    })
    assert event is not None
    assert event["direction"] == "entry"
    assert len(event["event_uid"]) == 64


def test_multiple_device_configuration_uses_isolated_state_files(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("""{
      "erp_base_url": "https://erp.example.test",
      "devices": [
        {
          "hikvision_base_url": "https://10.100.50.73",
          "hikvision_cert_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "device_key": "turnstile-73"
        },
        {
          "hikvision_base_url": "https://10.100.50.31",
          "hikvision_cert_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "device_key": "turnstile-31",
          "sync_photos": false
        }
      ]
    }""", encoding="utf-8")
    monkeypatch.setenv("HIKVISION_USERNAME", "admin")
    monkeypatch.setenv("HIKVISION_PASSWORD", "secret")
    monkeypatch.setenv("ATTENDANCE_INTEGRATION_TOKEN", "token")

    configs = Config.from_files_all(config_path)

    assert [item.device_key for item in configs] == ["turnstile-73", "turnstile-31"]
    assert [item.sync_photos for item in configs] == [True, False]
    assert [item.state_path for item in configs] == [
        str(tmp_path / "state.turnstile-73.json"),
        str(tmp_path / "state.turnstile-31.json"),
    ]


def test_hikvision_xml_response_is_normalized_to_the_json_shape():
    response = httpx.Response(
        200,
        content=b"""<?xml version="1.0" encoding="UTF-8"?>
        <UserInfoCount xmlns="http://www.hikvision.com/ver20/XMLSchema">
          <userNumber>1500</userNumber>
        </UserInfoCount>""",
        request=httpx.Request("GET", "https://turnstile.test/ISAPI/AccessControl/UserInfo/Count"),
    )

    assert response_json(response) == {"UserInfoCount": {"userNumber": "1500"}}


def test_initial_event_history_is_read_in_daily_windows(tmp_path):
    connector_config = config()
    connector_config.initial_event_days = 3
    connector_config.state_path = str(tmp_path / "state.json")

    class FakeHikvision:
        calls = []

        def device_info(self):
            return {"DeviceInfo": {"model": "test"}}

        def person_count(self):
            return 1500

        def events(self, start, end):
            self.calls.append((start, end))
            return []

    class FakeErp:
        calls = 0

        def events(self, device, events):
            self.calls += 1
            return {"inserted": 0, "duplicates": 0}

    hikvision = FakeHikvision()
    erp = FakeErp()
    state = {"version": 1, "photo_hashes": {}}

    sync_events(connector_config, hikvision, erp, state)

    assert len(hikvision.calls) == 3
    assert all((end - start).total_seconds() <= 86_400 for start, end in hikvision.calls)
    assert erp.calls == 1
    assert "last_event_cursor" in state
