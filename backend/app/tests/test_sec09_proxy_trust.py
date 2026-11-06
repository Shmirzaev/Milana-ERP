import pytest
from starlette.requests import Request

from app.api.routes import auth
import app.main as main


def request(peer, fields, scheme="http"):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(k.encode(), v.encode()) for k, v in fields],
                    "client": (peer, 50000), "scheme": scheme, "server": ("erp.example", 80), "query_string": b""})


@pytest.mark.parametrize("resolve", [auth._client_ip, main._rate_limit_client_key])
@pytest.mark.parametrize("peer", ["127.0.0.1", "10.20.30.40"])
def test_private_peer_is_not_implicitly_trusted(monkeypatch, resolve, peer):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert resolve(request(peer, [("x-forwarded-for", "198.51.100.10")])) == peer


@pytest.mark.parametrize("resolve", [auth._client_ip, main._rate_limit_client_key])
@pytest.mark.parametrize("fields", [
    [("x-forwarded-for", "203.0.113.66, 198.51.100.10")],
    [("x-forwarded-for", "203.0.113.66"), ("x-forwarded-for", "198.51.100.10")],
])
def test_nearest_untrusted_hop_wins_in_wire_order(monkeypatch, resolve, fields):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    assert resolve(request("127.0.0.1", fields)) == "198.51.100.10"


@pytest.mark.parametrize("resolve", [auth._client_ip, main._rate_limit_client_key])
@pytest.mark.parametrize("chain", ["198.51.100.10,,10.1.1.1", "198.51.100.10,garbage"])
def test_malformed_chain_falls_back_to_socket(monkeypatch, resolve, chain):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,10.0.0.0/8")
    assert resolve(request("127.0.0.1", [("x-forwarded-for", chain)])) == "127.0.0.1"


def test_untrusted_forwarding_cannot_change_cookie_or_csrf_scheme(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    req = request("8.8.8.8", [("host", "erp.example"), ("x-forwarded-proto", "https")])
    assert auth._is_https_request(req) is False
    assert "https://erp.example" not in main._trusted_csrf_origins(req)


def test_trusted_duplicate_proto_uses_last_proxy_field(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    req = request("127.0.0.1", [("host", "erp.example"), ("x-forwarded-proto", "http"), ("x-forwarded-proto", "https")])
    assert auth._is_https_request(req) is True
    assert "https://erp.example" in main._trusted_csrf_origins(req)


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "::/0", "10.20.30.40/16", "not-a-network"])
def test_runtime_rejects_trust_all_and_invalid_cidrs(monkeypatch, cidr):
    from app.core.proxy_trust import validate_proxy_runtime_configuration
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", cidr)
    with pytest.raises(RuntimeError, match="valid, non-default IP networks"):
        validate_proxy_runtime_configuration(strict_security_required=False)


def test_hosted_runtime_requires_explicit_proxy_ownership(monkeypatch):
    from app.core.proxy_trust import validate_proxy_runtime_configuration
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        validate_proxy_runtime_configuration(strict_security_required=True)
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    with pytest.raises(RuntimeError, match="FORWARDED_ALLOW_IPS"):
        validate_proxy_runtime_configuration(strict_security_required=True)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    validate_proxy_runtime_configuration(strict_security_required=True)
