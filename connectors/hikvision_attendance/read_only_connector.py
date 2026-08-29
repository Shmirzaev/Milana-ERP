#!/usr/bin/env python3
"""Read-only Hikvision attendance mirror connector.

The Hikvision transport deliberately permits only GET requests and three POST
search endpoints. There is no generic write method and no PUT/PATCH/DELETE
support in this process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPSHandler,
    Request as UrlRequest,
    build_opener,
)
from zoneinfo import ZoneInfo

import httpx


ALLOWED_SEARCH_PATHS = {
    "/ISAPI/AccessControl/UserInfo/Search",
    "/ISAPI/AccessControl/AcsEvent",
    "/ISAPI/Intelligent/FDLib/FDSearch",
}
ALLOWED_DEVICE_GET_PREFIXES = ("/ISAPI/", "/LOCALS/pic/enrlFace/")
STATE_VERSION = 1


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


def _xml_tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _xml_value(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        return text
    result: dict[str, Any] = {}
    for child in children:
        key = _xml_tag(child.tag)
        value = _xml_value(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        if response.content.lstrip().startswith(b"<"):
            try:
                root = ET.fromstring(response.content)
                return {_xml_tag(root.tag): _xml_value(root)}
            except ET.ParseError:
                pass
        content_type = response.headers.get("content-type", "unknown")
        prefix = response.content[:32].hex()
        raise RuntimeError(
            f"Expected JSON from {response.request.method} {response.request.url}; "
            f"received {content_type} ({len(response.content)} bytes; prefix {prefix})"
        ) from exc


def _clean_fingerprint(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch in "0123456789abcdef")


def device_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # One installed lane uses an older AES-SHA suite. Certificate pinning below
    # remains mandatory, so allowing that suite does not remove peer identity
    # verification from the connector.
    context.set_ciphers("DEFAULT:@SECLEVEL=0")
    return context


def peer_certificate_sha256(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("HIKVISION_BASE_URL must be an https URL")
    port = parsed.port or 443
    context = device_ssl_context()
    for attempt in range(1, 4):
        try:
            with socket.create_connection((parsed.hostname, port), timeout=10) as raw:
                with context.wrap_socket(raw, server_hostname=parsed.hostname) as secured:
                    certificate = secured.getpeercert(binary_form=True)
            return hashlib.sha256(certificate).hexdigest()
        except (OSError, ssl.SSLError, TimeoutError):
            if attempt == 3:
                raise
            log(f"Retrying Hikvision certificate pin check ({attempt}/3): {parsed.hostname}")
            time.sleep(attempt)
    raise RuntimeError("Unreachable certificate retry state")


@dataclass
class Config:
    hikvision_base_url: str
    hikvision_username: str
    hikvision_password: str
    hikvision_cert_sha256: str
    erp_base_url: str
    erp_token: str
    device_key: str = "main-turnstile"
    device_name: str = "Main turnstile"
    initial_event_days: int = 30
    people_sync_hours: int = 24
    page_size: int = 30
    state_path: str = "state.json"
    sync_photos: bool = True

    @classmethod
    def from_files_all(cls, config_path: Path, secrets_path: Path | None = None) -> list["Config"]:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        secrets: dict[str, Any] = {}
        if secrets_path and secrets_path.exists():
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        username = os.environ.get("HIKVISION_USERNAME") or secrets.get("hikvision_username")
        password = os.environ.get("HIKVISION_PASSWORD") or secrets.get("hikvision_password")
        token = os.environ.get("ATTENDANCE_INTEGRATION_TOKEN") or secrets.get("erp_token")
        if not username or not password or not token:
            raise RuntimeError("Hikvision username/password and ERP integration token are required")
        device_rows = raw.get("devices")
        if device_rows is None:
            device_rows = [raw]
        if not isinstance(device_rows, list) or not device_rows:
            raise RuntimeError("At least one Hikvision device is required")
        configs: list[Config] = []
        seen_keys: set[str] = set()
        for index, device_raw in enumerate(device_rows, start=1):
            if not isinstance(device_raw, dict):
                raise RuntimeError(f"Device configuration #{index} must be an object")
            combined = {**raw, **device_raw}
            device_key = str(combined.get("device_key", f"turnstile-{index}"))
            if device_key in seen_keys:
                raise RuntimeError(f"Duplicate Hikvision device key: {device_key}")
            seen_keys.add(device_key)
            default_state = "state.json" if len(device_rows) == 1 else f"state.{device_key}.json"
            state_path = Path(combined.get("state_path", default_state))
            if not state_path.is_absolute():
                state_path = config_path.parent / state_path
            configs.append(cls(
                hikvision_base_url=str(combined["hikvision_base_url"]).rstrip("/"),
                hikvision_username=str(username),
                hikvision_password=str(password),
                hikvision_cert_sha256=str(combined["hikvision_cert_sha256"]),
                erp_base_url=str(combined["erp_base_url"]).rstrip("/"),
                erp_token=str(token),
                device_key=device_key,
                device_name=str(combined.get("device_name", f"Turnstile {index}")),
                initial_event_days=max(1, min(int(combined.get("initial_event_days", 30)), 90)),
                people_sync_hours=max(1, int(combined.get("people_sync_hours", 24))),
                page_size=max(10, min(int(combined.get("page_size", 30)), 100)),
                state_path=str(state_path),
                sync_photos=bool(combined.get("sync_photos", True)),
            ))
        return configs

    @classmethod
    def from_files(cls, config_path: Path, secrets_path: Path | None = None) -> "Config":
        configs = cls.from_files_all(config_path, secrets_path)
        if len(configs) != 1:
            raise RuntimeError("Configuration contains multiple Hikvision devices; use from_files_all")
        return configs[0]

    def validate(self) -> None:
        device = urlparse(self.hikvision_base_url)
        erp = urlparse(self.erp_base_url)
        if device.scheme != "https" or not device.hostname:
            raise RuntimeError("Hikvision URL must use HTTPS")
        if erp.scheme != "https" or not erp.hostname:
            raise RuntimeError("ERP URL must use HTTPS")
        actual = peer_certificate_sha256(self.hikvision_base_url)
        expected = _clean_fingerprint(self.hikvision_cert_sha256)
        if len(expected) != 64 or not hashlib.sha256(bytes.fromhex(expected)).digest():
            raise RuntimeError("Invalid Hikvision certificate SHA-256 fingerprint")
        if not hmac_compare(actual, expected):
            raise RuntimeError(
                "Hikvision TLS certificate fingerprint changed; refusing to connect. "
                f"Expected {expected}, received {actual}."
            )


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.encode(), right.encode())


class ReadOnlyHikvision:
    def __init__(self, config: Config):
        self.config = config
        self._origin = urlparse(config.hikvision_base_url)
        self._fallback_paths: set[str] = set()
        self.client = httpx.Client(
            base_url=config.hikvision_base_url,
            auth=httpx.DigestAuth(config.hikvision_username, config.hikvision_password),
            verify=device_ssl_context(),
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=False,
            headers={"Connection": "close"},
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, 4):
            try:
                response = self.client.request(method, path, **kwargs)
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 3:
                    response.raise_for_status()
                    return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt == 3:
                    raise
            log(f"Retrying read-only device request ({attempt}/3): {method} {urlparse(path).path}")
            time.sleep(attempt)
        raise RuntimeError("Unreachable device retry state")

    def _urllib_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        target = urljoin(f"{self.config.hikvision_base_url}/", path)
        password_manager = HTTPPasswordMgrWithDefaultRealm()
        password_manager.add_password(
            None,
            self.config.hikvision_base_url,
            self.config.hikvision_username,
            self.config.hikvision_password,
        )
        opener = build_opener(
            HTTPSHandler(context=device_ssl_context()),
            HTTPDigestAuthHandler(password_manager),
        )
        data = json.dumps(payload).encode() if payload is not None else None
        request = UrlRequest(
            target,
            data=data,
            headers={"Content-Type": "application/json", "Connection": "close"},
            method=method,
        )
        try:
            with opener.open(request, timeout=60) as opened:
                response = httpx.Response(
                    opened.status,
                    content=opened.read(),
                    headers=dict(opened.headers.items()),
                    request=httpx.Request(method, target),
                )
        except HTTPError as exc:
            response = httpx.Response(
                exc.code,
                content=exc.read(),
                headers=dict(exc.headers.items()),
                request=httpx.Request(method, target),
            )
        except URLError as exc:
            raise RuntimeError(f"Fallback device transport failed: {exc.reason}") from exc
        response.raise_for_status()
        return response

    def get(self, path_or_url: str) -> httpx.Response:
        target = urlparse(urljoin(f"{self.config.hikvision_base_url}/", path_or_url))
        if target.hostname != self._origin.hostname:
            raise RuntimeError("Device returned a photo URL outside the pinned Hikvision origin")
        if not target.path.startswith(ALLOWED_DEVICE_GET_PREFIXES):
            raise RuntimeError(f"Blocked unapproved device GET path: {target.path}")
        safe_target = target.path + (f"?{target.query}" if target.query else "")
        if target.path in self._fallback_paths:
            return self._urllib_request("GET", safe_target)
        try:
            return self._request("GET", safe_target)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            log(f"Switching to fallback read-only transport: GET {target.path}")
            self._fallback_paths.add(target.path)
            return self._urllib_request("GET", safe_target)

    def post_search(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        parsed = urlparse(path)
        if parsed.path not in ALLOWED_SEARCH_PATHS:
            raise RuntimeError(f"Blocked non-read-only Hikvision POST path: {parsed.path}")
        if parsed.path in self._fallback_paths:
            return response_json(self._urllib_request("POST", path, payload))
        try:
            response = self._request("POST", path, json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            log(f"Switching to fallback read-only transport: POST {parsed.path}")
            self._fallback_paths.add(parsed.path)
            response = self._urllib_request("POST", path, payload)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            log(f"Switching to fallback read-only transport: POST {parsed.path}")
            self._fallback_paths.add(parsed.path)
            response = self._urllib_request("POST", path, payload)
        return response_json(response)

    def device_info(self) -> dict[str, Any]:
        return response_json(self.get("/ISAPI/System/deviceInfo?format=json"))

    def person_count(self) -> int | None:
        data = response_json(self.get("/ISAPI/AccessControl/UserInfo/Count?format=json"))
        root = data.get("UserInfoCount") or data
        for key in ("userNumber", "totalMatches", "total"):
            if root.get(key) is not None:
                return int(root[key])
        return None

    def people(self) -> list[dict[str, Any]]:
        search_id = str(uuid.uuid4())
        position = 0
        result: list[dict[str, Any]] = []
        while True:
            payload = {"UserInfoSearchCond": {
                "searchID": search_id,
                "searchResultPosition": position,
                "maxResults": self.config.page_size,
            }}
            data = self.post_search("/ISAPI/AccessControl/UserInfo/Search?format=json", payload)
            root = data.get("UserInfoSearch") or data.get("UserInfoSearchResult") or data
            page = root.get("UserInfo") or root.get("userInfo") or []
            if isinstance(page, dict):
                page = [page]
            result.extend(page)
            matches = int(root.get("numOfMatches", len(page)) or 0)
            total = int(root.get("totalMatches", len(result)) or len(result))
            if position == 0:
                log(f"Device profile list reports {total} matching records")
            position += matches
            if position and position % 1000 == 0:
                log(f"Read {position}/{total} employee profiles from device")
            if matches == 0 or position >= total:
                break
        return result

    def face_urls(self) -> dict[str, str]:
        search_id = str(uuid.uuid4())
        position = 0
        result: dict[str, str] = {}
        while True:
            payload = {"FDSearchDescription": {
                "searchID": search_id,
                "searchResultPosition": position,
                "maxResults": self.config.page_size,
                "faceLibType": "blackFD",
                "FDID": "1",
            }}
            data = self.post_search("/ISAPI/Intelligent/FDLib/FDSearch?format=json", payload)
            root = data.get("FDSearchResult") or data.get("FDSearch") or data
            page = root.get("MatchList") or root.get("matchList") or []
            if isinstance(page, dict):
                page = page.get("MatchElement") or page.get("matchElement") or [page]
            if isinstance(page, dict):
                page = [page]
            for item in page:
                person_id = str(item.get("FPID") or item.get("employeeNo") or "").strip()
                url = item.get("faceURL") or item.get("faceUrl")
                if person_id and url:
                    result[person_id] = str(url)
            matches = int(root.get("numOfMatches", len(page)) or 0)
            total = int(root.get("totalMatches", len(result)) or len(result))
            if position == 0:
                log(f"Event window reports {total} matching records")
            position += matches
            if position and position % 1000 == 0:
                log(f"Read {position}/{total} attendance events from device")
            if matches == 0 or position >= total:
                break
        return result

    def events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        search_id = str(uuid.uuid4())
        position = 0
        result: list[dict[str, Any]] = []
        while True:
            payload = {"AcsEventCond": {
                "searchID": search_id,
                "searchResultPosition": position,
                "maxResults": self.config.page_size,
                "major": 0,
                "minor": 0,
                "startTime": start.astimezone(ZoneInfo("Asia/Tashkent")).isoformat(timespec="seconds"),
                "endTime": end.astimezone(ZoneInfo("Asia/Tashkent")).isoformat(timespec="seconds"),
            }}
            data = self.post_search("/ISAPI/AccessControl/AcsEvent?format=json", payload)
            root = data.get("AcsEvent") or data.get("AcsEventSearchResult") or data
            page = root.get("InfoList") or root.get("infoList") or []
            if isinstance(page, dict):
                page = page.get("AcsEventInfo") or page.get("acsEventInfo") or [page]
            if isinstance(page, dict):
                page = [page]
            result.extend(page)
            matches = int(root.get("numOfMatches", len(page)) or 0)
            total = int(root.get("totalMatches", len(result)) or len(result))
            position += matches
            if matches == 0 or position >= total:
                break
        return result


class ErpMirror:
    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(
            base_url=config.erp_base_url,
            headers={"X-Attendance-Token": config.erp_token},
            verify=True,
            timeout=httpx.Timeout(60, connect=15),
        )

    def close(self) -> None:
        self.client.close()

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response_json(response)

    def people(self, device: dict[str, Any], people: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post_json("/api/attendance/integration/people", {
            "device": device,
            "people": people,
            "full_snapshot": True,
        })

    def events(self, device: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post_json("/api/attendance/integration/events", {"device": device, "events": events})

    def photo(self, device_key: str, person_id: str, data: bytes, content_type: str) -> dict[str, Any]:
        path = f"/api/attendance/integration/photos/{quote(device_key, safe='')}/{quote(person_id, safe='')}"
        response = self.client.post(path, content=data, headers={"Content-Type": content_type or "application/octet-stream"})
        response.raise_for_status()
        return response_json(response)


def _first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _parse_dt(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def normalize_person(raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    person_id = str(_first(raw, "employeeNo", "employeeNoString", "FPID", default="")).strip()
    if not person_id:
        raise ValueError("Hikvision user record has no employee number")
    validity = raw.get("Valid") or raw.get("valid") or {}
    face_url = _first(raw, "faceURL", "faceUrl")
    face_count = int(_first(raw, "numOfFace", "faceCount", default=1 if face_url else 0) or 0)
    person = {
        "external_person_id": person_id,
        "full_name": str(_first(raw, "name", default=person_id)).strip() or person_id,
        "user_type": str(_first(raw, "userType", default="normal")).strip() or None,
        "valid_from": _parse_dt(_first(validity, "beginTime", "startTime")),
        "valid_to": _parse_dt(_first(validity, "endTime", "stopTime")),
        "is_valid": bool(_first(validity, "enable", default=True)),
        "has_face": face_count > 0,
        "card_count": int(_first(raw, "numOfCard", "cardCount", default=0) or 0),
        "fingerprint_count": int(_first(raw, "numOfFP", "fingerPrintCount", default=0) or 0),
    }
    return person, str(face_url) if face_url else None


def normalize_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    occurred = _parse_dt(_first(raw, "time", "dateTime", "eventTime"))
    if not occurred:
        return None
    person_id = str(_first(raw, "employeeNoString", "employeeNo", "cardNo", default="")).strip() or None
    direction_raw = str(_first(raw, "attendanceStatus", "direction", default="")).lower()
    direction = "entry" if direction_raw in {"checkin", "check_in", "in", "entry"} else (
        "exit" if direction_raw in {"checkout", "check_out", "out", "exit"} else "unknown"
    )
    identity = {
        "serial": _first(raw, "serialNo", "serialNumber"),
        "time": occurred,
        "person": person_id,
        "door": _first(raw, "doorNo"),
        "reader": _first(raw, "cardReaderNo", "readerNo"),
        "major": _first(raw, "major"),
        "minor": _first(raw, "minor"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "event_uid": digest,
        "external_person_id": person_id,
        "occurred_at": occurred,
        "direction": direction,
        "verification_mode": str(_first(raw, "currentVerifyMode", "verifyMode", default="")).strip() or None,
        "result": str(_first(raw, "status", "eventStatus", default="success")).strip() or None,
        "door_no": _int_or_none(_first(raw, "doorNo")),
        "reader_no": _int_or_none(_first(raw, "cardReaderNo", "readerNo")),
        "serial_no": _int_or_none(_first(raw, "serialNo", "serialNumber")),
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def device_payload(config: Config, info: dict[str, Any], count: int | None) -> dict[str, Any]:
    root = info.get("DeviceInfo") or info
    return {
        "device_key": config.device_key,
        "name": config.device_name,
        "vendor": "Hikvision",
        "model": _first(root, "model", "deviceType"),
        "serial_no": _first(root, "serialNumber", "deviceID"),
        "source_host": urlparse(config.hikvision_base_url).hostname,
        "reported_person_count": count,
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "photo_hashes": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if state.get("version") == STATE_VERSION else {"version": STATE_VERSION, "photo_hashes": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": STATE_VERSION, "photo_hashes": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def chunks(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def sync_people(config: Config, hik: ReadOnlyHikvision, erp: ErpMirror, state: dict[str, Any]) -> None:
    info = hik.device_info()
    count = hik.person_count()
    raw_people = hik.people()
    people: list[dict[str, Any]] = []
    inline_face_urls: dict[str, str] = {}
    for raw in raw_people:
        try:
            person, face_url = normalize_person(raw)
        except ValueError as exc:
            log(f"Skipping invalid device profile: {exc}")
            continue
        people.append(person)
        if face_url:
            inline_face_urls[person["external_person_id"]] = face_url
    if count is not None and count != len(people):
        raise RuntimeError(f"Device reported {count} people but search returned {len(people)}; snapshot was not uploaded")
    device = device_payload(config, info, count)
    result = erp.people(device, people)
    log(f"People mirror: {result['received']} received, {result['created']} new, {result['updated']} updated")

    if not config.sync_photos:
        state["last_people_sync_at"] = datetime.now(timezone.utc).isoformat()
        save_state(Path(config.state_path), state)
        log("Photo mirror skipped for this lane; employee photos come from the designated profile device")
        return

    face_urls = dict(inline_face_urls)
    try:
        face_urls.update(hik.face_urls())
    except Exception as exc:
        log(f"Face index search unavailable; continuing with profile face URLs: {exc}")
    photo_hashes = state.setdefault("photo_hashes", {})
    skip_existing_photos = os.environ.get("ATTENDANCE_SKIP_EXISTING_PHOTOS") == "1"
    uploaded = 0
    failed = 0
    for index, person in enumerate(people, start=1):
        person_id = person["external_person_id"]
        url = face_urls.get(person_id)
        if not url:
            continue
        if skip_existing_photos and person_id in photo_hashes:
            continue
        try:
            response = hik.get(url)
            data = response.content
            time.sleep(0.25)
            digest = hashlib.sha256(data).hexdigest()
            if photo_hashes.get(person_id) == digest:
                continue
            erp.photo(config.device_key, person_id, data, response.headers.get("content-type", ""))
            photo_hashes[person_id] = digest
            uploaded += 1
            if uploaded % 100 == 0:
                save_state(Path(config.state_path), state)
                log(f"Uploaded {uploaded} changed profile photos ({index}/{len(people)} checked)")
        except Exception as exc:
            failed += 1
            if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code not in {400, 404}:
                log(f"Photo import failed for employee {person_id}: {exc}")
    state["last_people_sync_at"] = datetime.now(timezone.utc).isoformat()
    save_state(Path(config.state_path), state)
    log(f"Photo mirror: {uploaded} changed photos uploaded, {failed} failed")


def sync_events(config: Config, hik: ReadOnlyHikvision, erp: ErpMirror, state: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    saved = _parse_dt(state.get("last_event_cursor"))
    if saved:
        start = datetime.fromisoformat(saved) - timedelta(minutes=5)
    else:
        start = now - timedelta(days=config.initial_event_days)
    info = hik.device_info()
    count = hik.person_count()
    device = device_payload(config, info, count)
    received = inserted = duplicates = 0
    window_start = start
    while window_start < now:
        window_end = min(window_start + timedelta(days=1), now)
        raw_events = hik.events(window_start, window_end)
        events = [normalized for raw in raw_events if (normalized := normalize_event(raw))]
        for batch in chunks(events, 1000):
            result = erp.events(device, batch)
            inserted += int(result["inserted"])
            duplicates += int(result["duplicates"])
        received += len(events)
        state["last_event_cursor"] = window_end.isoformat()
        save_state(Path(config.state_path), state)
        window_start = window_end
    if not received:
        erp.events(device, [])
    log(f"Event mirror: {received} received from device, {inserted} new, {duplicates} duplicates")


def should_sync_people(config: Config, state: dict[str, Any]) -> bool:
    previous = _parse_dt(state.get("last_people_sync_at"))
    if not previous:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(previous) >= timedelta(hours=config.people_sync_hours)


def run_sync(config: Config, mode: str) -> None:
    config.validate()
    state_path = Path(config.state_path)
    state = load_state(state_path)
    hik = ReadOnlyHikvision(config)
    erp = ErpMirror(config)
    try:
        if mode in {"people", "all"} or (mode == "scheduled" and should_sync_people(config, state)):
            sync_people(config, hik, erp, state)
        if mode in {"events", "all", "scheduled"}:
            sync_events(config, hik, erp, state)
    finally:
        hik.close()
        erp.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Hikvision attendance mirror")
    parser.add_argument("mode", choices=["fingerprint", "people", "events", "all", "scheduled"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secrets")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.mode == "fingerprint":
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        device_rows = raw.get("devices") or [raw]
        fingerprints = [{
            "device_key": str(device.get("device_key", f"turnstile-{index}")),
            "hikvision_base_url": str(device["hikvision_base_url"]),
            "hikvision_cert_sha256": peer_certificate_sha256(str(device["hikvision_base_url"])),
        } for index, device in enumerate(device_rows, start=1)]
        if len(fingerprints) == 1:
            print(fingerprints[0]["hikvision_cert_sha256"])
        else:
            print(json.dumps(fingerprints))
        return 0
    configs = Config.from_files_all(config_path, Path(args.secrets).resolve() if args.secrets else None)
    failures: list[str] = []
    for config in configs:
        log(f"Syncing {config.device_name} ({urlparse(config.hikvision_base_url).hostname})")
        try:
            run_sync(config, args.mode)
        except Exception as exc:
            failures.append(f"{config.device_key}: {exc}")
            log(f"Device sync failed for {config.device_key}: {exc}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise SystemExit(1)
