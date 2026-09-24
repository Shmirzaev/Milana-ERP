from functools import lru_cache
import ipaddress
import os

from fastapi import Request


TRUSTED_PROXY_CIDRS_ENV = "TRUSTED_PROXY_CIDRS"
UVICORN_FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"


@lru_cache(maxsize=32)
def _parse_trusted_proxy_cidrs(raw_value: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in raw_value.split(","):
        value = value.strip()
        if not value:
            continue
        network = ipaddress.ip_network(value, strict=True)
        if network.prefixlen == 0:
            raise ValueError("proxy trust must not include every IPv4 or IPv6 address")
        networks.append(network)
    return tuple(networks)


def trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Return the explicitly configured proxy networks.

    An empty value deliberately trusts no forwarding peer.  Reading the
    environment here, instead of freezing it at module import time, also keeps
    worker/test configuration deterministic.
    """
    return _parse_trusted_proxy_cidrs(os.environ.get(TRUSTED_PROXY_CIDRS_ENV, ""))


def validate_proxy_runtime_configuration(*, strict_security_required: bool) -> None:
    """Fail closed when a hosted runtime has ambiguous proxy ownership.

    Uvicorn otherwise trusts loopback forwarding headers before the request
    reaches this application, which discards the socket peer needed for an
    application-level allowlist decision.  Hosted deployments must disable
    that implicit layer and configure the exact proxy CIDRs here instead.
    """
    raw_cidrs = os.environ.get(TRUSTED_PROXY_CIDRS_ENV, "")
    try:
        networks = _parse_trusted_proxy_cidrs(raw_cidrs)
    except ValueError as exc:
        raise RuntimeError(
            f"{TRUSTED_PROXY_CIDRS_ENV} must contain valid, non-default IP networks"
        ) from exc

    if not strict_security_required:
        return

    errors: list[str] = []
    if not networks:
        errors.append(f"{TRUSTED_PROXY_CIDRS_ENV} must list the exact trusted reverse-proxy networks")
    if os.environ.get(UVICORN_FORWARDED_ALLOW_IPS_ENV) != "":
        errors.append(
            f"{UVICORN_FORWARDED_ALLOW_IPS_ENV} must be explicitly empty so only "
            f"{TRUSTED_PROXY_CIDRS_ENV} controls forwarding-header trust"
        )
    if errors:
        raise RuntimeError("Unsafe proxy configuration: " + "; ".join(errors))


def _peer_ip(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    peer = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(peer)
    except ValueError:
        return None


def is_trusted_proxy_peer(request: Request) -> bool:
    peer = _peer_ip(request)
    return peer is not None and any(peer in network for network in trusted_proxy_networks())


def client_ip(request: Request) -> str:
    """Resolve a client address without accepting a spoofable proxy hop.

    Walk X-Forwarded-For from the socket peer toward the client and stop at
    the first untrusted address.  Malformed chains fail closed to the actual
    peer rather than partially trusting attacker-controlled input.
    """
    peer = request.client.host if request.client else "unknown"
    if not is_trusted_proxy_peer(request):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        try:
            values = [value.strip() for value in forwarded.split(",")]
            if any(not value for value in values):
                return peer
            hops = [ipaddress.ip_address(value) for value in values]
        except ValueError:
            return peer
        if not hops:
            return peer
        networks = trusted_proxy_networks()
        for hop in reversed(hops):
            if not any(hop in network for network in networks):
                return str(hop)
        return str(hops[0])

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        try:
            return str(ipaddress.ip_address(real_ip))
        except ValueError:
            return peer
    return peer


def forwarded_scheme(request: Request) -> str | None:
    """Return a proxy-provided scheme only for an explicitly trusted peer."""
    if not is_trusted_proxy_peer(request):
        return None
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        # The immediate proxy is the right-most hop when intermediaries append.
        scheme = forwarded.rsplit(",", 1)[-1].strip().lower()
        if scheme in {"http", "https"}:
            return scheme
    forwarded_ssl = request.headers.get("x-forwarded-ssl", "").strip().lower()
    if forwarded_ssl == "on":
        return "https"
    return None


def effective_request_scheme(request: Request) -> str:
    return forwarded_scheme(request) or request.url.scheme.lower()
