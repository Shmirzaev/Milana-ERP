"""The reader must never become a write/configuration or foreign-host client.

All HTTP traffic here uses in-memory transports, including urllib redirects.
Neither terminals nor either ERP is contacted by these regression cases.
"""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl
from unittest.mock import Mock

import httpx
import pytest

import read_only_connector as connector
from test_read_only_connector import config


@pytest.fixture
def device():
    hik = connector.ReadOnlyHikvision(config())
    hik.client.close()
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={"result": "read"})

    hik.client = httpx.Client(
        base_url=hik.config.hikvision_base_url,
        transport=httpx.MockTransport(reply),
        follow_redirects=False,
    )
    try:
        yield hik, requests
    finally:
        hik.close()


@pytest.mark.parametrize("entry", ["get", "post_search", "httpx", "urllib"])
@pytest.mark.parametrize("url", [
    "https://previous-erp.example:8443/ISAPI/AccessControl/UserInfo/Search?format=json",
    "//previous-erp.example/ISAPI/AccessControl/UserInfo/Search?format=json",
    "http://10.100.50.41/ISAPI/AccessControl/UserInfo/Search?format=json",
    "https://10.100.50.41:8443/ISAPI/AccessControl/UserInfo/Search?format=json",
    "https://unused:unused@10.100.50.41/ISAPI/AccessControl/UserInfo/Search?format=json",
    "https://10.100.50.41:0/ISAPI/AccessControl/UserInfo/Search?format=json",
    "https://10.100.50.41/ISAPI/AccessControl/UserInfo/Search?format=json#unapproved",
])
def test_every_transport_rejects_unpinned_origin_before_io(device, monkeypatch, entry, url):
    hik, requests = device
    opener = Mock(side_effect=AssertionError("Unapproved URL reached urllib"))
    monkeypatch.setattr(connector, "build_opener", opener)
    with pytest.raises(RuntimeError, match="pinned Hikvision origin"):
        if entry == "get":
            hik.get(url)
        elif entry == "post_search":
            hik.post_search(url, {})
        elif entry == "httpx":
            hik._request("POST", url, json={})
        else:
            hik._urllib_request("POST", url, {})
    assert not requests and not opener.called


@pytest.mark.parametrize("entry", ["httpx", "urllib"])
@pytest.mark.parametrize("method,path", [
    ("PUT", "/ISAPI/AccessControl/UserInfo/Modify?format=json"),
    ("PUT", "/ISAPI/AccessControl/RemoteControl/door/1"),
    ("DELETE", "/ISAPI/Intelligent/FDLib/1/picture/1"),
    ("POST", "/ISAPI/AccessControl/UserInfo/Record?format=json"),
    ("PUT", "/ISAPI/AccessControl/UserInfoDetail/Delete?format=json"),
    ("POST", "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json"),
    ("PUT", "/ISAPI/AccessControl/DeployInfo"),
    ("PUT", "/ISAPI/System/Network/httpHosts"),
])
def test_write_and_disconnect_commands_never_reach_io(device, monkeypatch, entry, method, path):
    hik, requests = device
    opener = Mock(side_effect=AssertionError("Forbidden command reached urllib"))
    monkeypatch.setattr(connector, "build_opener", opener)
    with pytest.raises(RuntimeError, match="Blocked"):
        if entry == "httpx":
            hik._request(method, path, json={})
        else:
            hik._urllib_request(method, path, {})
    assert not requests and not opener.called


@pytest.mark.parametrize("absolute", [False, True])
@pytest.mark.parametrize("path", sorted(connector.ALLOWED_SEARCH_PATHS))
def test_approved_search_preserves_query_payload_and_origin(device, absolute, path):
    hik, requests = device
    target = path + "?format=json"
    payload = {"searchID": "synthetic", "maxResults": 10}
    url = hik.config.hikvision_base_url + ":443" + target if absolute else target
    assert hik.post_search(url, payload) == {"result": "read"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == hik.config.hikvision_base_url + target
    assert request.content == httpx.Request("POST", url, json=payload).content


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("destination", [
    "https://previous-erp.example:8443/ISAPI/System/deviceInfo",
    "https://10.100.50.41/ISAPI/AccessControl/UserInfo/Record?format=json",
])
def test_fallback_redirect_cannot_reach_previous_erp(device, monkeypatch, status, destination, method):
    hik, _ = device
    requests = []

    class SyntheticHTTPS(HTTPSHandler):
        def https_open(self, request):
            requests.append(request.full_url)
            headers = Message()
            if len(requests) == 1:
                headers["Location"] = destination
                response = addinfourl(io.BytesIO(b""), headers, request.full_url, status)
                response.msg = "Redirect"
            else:
                response = addinfourl(io.BytesIO(b"{}"), headers, request.full_url, 200)
                response.msg = "OK"
            return response

    def synthetic_opener(*handlers):
        # Use the real urllib chain/redirect processor but no sockets or TLS.
        handlers = [h for h in handlers if not isinstance(h, HTTPSHandler)]
        return build_opener(SyntheticHTTPS(), *handlers)

    monkeypatch.setattr(connector, "build_opener", synthetic_opener)
    path = "/ISAPI/System/deviceInfo" if method == "GET" else "/ISAPI/AccessControl/UserInfo/Search?format=json"
    with pytest.raises(RuntimeError, match="redirect"):
        hik._urllib_request(method, path, {} if method == "POST" else None)
    assert requests == [hik.config.hikvision_base_url + path]


@pytest.mark.parametrize("path", [
    "/ISAPI/../unapproved", "/ISAPI/%2e%2e/unapproved",
    "/ISAPI/%252e%252e/unapproved", "/ISAPI/%5c..%5cunapproved",
])
@pytest.mark.parametrize("entry", ["httpx", "urllib"])
def test_prefix_escape_is_rejected_before_io(device, monkeypatch, path, entry):
    hik, requests = device
    opener = Mock(side_effect=AssertionError("Unapproved path reached urllib"))
    monkeypatch.setattr(connector, "build_opener", opener)
    with pytest.raises(RuntimeError, match="Blocked"):
        if entry == "httpx":
            hik._request("GET", path)
        else:
            hik._urllib_request("GET", path)
    assert not requests and not opener.called


def test_httpx_never_follows_redirect_even_with_call_override(device):
    hik, requests = device

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://previous-erp.example/ISAPI/System/deviceInfo"})

    hik.client.close()
    hik.client = httpx.Client(base_url=hik.config.hikvision_base_url, transport=httpx.MockTransport(redirect))
    with pytest.raises(httpx.HTTPStatusError):
        hik._request("GET", "/ISAPI/System/deviceInfo", follow_redirects=True)
    assert len(requests) == 1 and requests[0].url.host == "10.100.50.41"


def test_httpx_digest_authentication_stays_on_the_configured_device(device):
    hik, requests = device

    def challenge(request):
        requests.append(request)
        if "authorization" not in request.headers:
            return httpx.Response(401, headers={
                "WWW-Authenticate": 'Digest realm="synthetic", nonce="123456789", algorithm=MD5, qop="auth"',
            })
        assert request.headers["authorization"].startswith("Digest ")
        return httpx.Response(200, json={"result": "read"})

    hik.client.close()
    hik.client = httpx.Client(
        base_url=hik.config.hikvision_base_url,
        transport=httpx.MockTransport(challenge),
        auth=httpx.DigestAuth("synthetic", "unused"),
    )
    assert hik.get("/ISAPI/System/deviceInfo?format=json").json() == {"result": "read"}
    assert len(requests) == 2
    assert all(r.method == "GET" and r.url.host == "10.100.50.41" for r in requests)


@pytest.mark.parametrize("path", [
    "/ISAPI/System/deviceInfo?format=json",
    "/LOCALS/pic/enrlFace/synthetic%20name.jpg?version=1",
])
def test_valid_get_preserves_path_query_and_https(device, path):
    hik, requests = device
    assert hik.get(hik.config.hikvision_base_url + path).status_code == 200
    assert len(requests) == 1
    assert str(requests[0].url) == hik.config.hikvision_base_url + path
    assert requests[0].method == "GET"


def test_configured_nondefault_https_port_remains_supported():
    cfg = config()
    cfg.hikvision_base_url = "https://device.example.test:9443"
    hik = connector.ReadOnlyHikvision(cfg)
    hik.client.close()
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={})

    hik.client = httpx.Client(base_url=cfg.hikvision_base_url, transport=httpx.MockTransport(reply))
    try:
        assert hik.get("/ISAPI/System/deviceInfo").status_code == 200
        with pytest.raises(RuntimeError, match="pinned Hikvision origin"):
            hik.get("https://device.example.test/ISAPI/System/deviceInfo")
        assert len(requests) == 1 and requests[0].url.port == 9443
    finally:
        hik.close()


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/ISAPI/System/deviceInfo?format=json", None),
    ("POST", "/ISAPI/AccessControl/UserInfo/Search?format=json", {"searchID": "synthetic"}),
])
def test_fallback_digest_challenge_preserves_read_and_search(device, monkeypatch, method, path, payload):
    hik, _ = device
    requests = []

    class SyntheticHTTPS(HTTPSHandler):
        def https_open(self, request):
            requests.append(request)
            headers = Message()
            if len(requests) == 1:
                headers["WWW-Authenticate"] = 'Digest realm="synthetic", nonce="123456789", algorithm=MD5, qop="auth"'
                response = addinfourl(io.BytesIO(b"{}"), headers, request.full_url, 401)
                response.msg = "Unauthorized"
            else:
                assert request.get_header("Authorization").startswith("Digest ")
                response = addinfourl(io.BytesIO(b'{"result":"read"}'), headers, request.full_url, 200)
                response.msg = "OK"
            return response

    def synthetic_opener(*handlers):
        handlers = [h for h in handlers if not isinstance(h, HTTPSHandler)]
        return build_opener(SyntheticHTTPS(), *handlers)

    monkeypatch.setattr(connector, "build_opener", synthetic_opener)
    response = hik._urllib_request(method, path, payload)
    assert response.json() == {"result": "read"}
    assert len(requests) == 2
    assert all(r.full_url == hik.config.hikvision_base_url + path and r.method == method for r in requests)
    if payload is not None:
        assert all(json.loads(r.data) == payload for r in requests)
        assert requests[0].data == requests[1].data


def test_bounded_parallel_reads_and_refusals_stay_isolated(device):
    hik, requests = device

    def attempt(index):
        if index % 2:
            with pytest.raises(RuntimeError):
                hik._request("PUT", "/ISAPI/AccessControl/DeployInfo", json={})
            return "refused"
        return hik.get("/ISAPI/System/deviceInfo?format=json").status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(100), timeout=5))
    assert results.count("refused") == results.count(200) == 50
    assert len(requests) == 50
    assert all(r.method == "GET" and r.url.host == "10.100.50.41" for r in requests)


def test_failed_lane_does_not_skip_later_devices(monkeypatch, tmp_path):
    devices = [config() for _ in range(6)]
    keys = ["turnstile-73", "turnstile-31", "turnstile-91", "main-turnstile", "turnstile-115", "turnstile-104"]
    for item, key in zip(devices, keys):
        item.device_key = key
    seen = []

    def sync(item, mode):
        assert mode == "scheduled"
        seen.append(item.device_key)
        if item.device_key == "main-turnstile":
            raise TimeoutError("synthetic unreachable lane")

    monkeypatch.setattr(connector.Config, "from_files_all", lambda *args: devices)
    monkeypatch.setattr(connector, "run_sync", sync)
    monkeypatch.setattr("sys.argv", ["reader", "scheduled", "--config", str(tmp_path / "unused.json")])
    with pytest.raises(RuntimeError, match="main-turnstile"):
        connector.main()
    assert seen == keys
