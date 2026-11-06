import importlib.util
from pathlib import Path
from unittest.mock import patch


SLOTCTL = Path(__file__).parents[3] / "deploy" / "slotctl.py"
spec = importlib.util.spec_from_file_location("slotctl_contract", SLOTCTL)
slotctl = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(slotctl)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_slotctl_uses_readiness_for_backend_and_keeps_liveness_warmup():
    urls = []

    def fake_urlopen(request_or_url, timeout=0):
        urls.append(request_or_url.full_url if hasattr(request_or_url, "full_url") else request_or_url)
        return _Response()

    with patch.object(slotctl.urllib.request, "urlopen", side_effect=fake_urlopen):
        slotctl.wait_for_health("backend", "blue", attempts=1)
        slotctl.warm("backend", "blue")
        slotctl.warm("frontend", "blue")

    assert urls[0].endswith(":18001/ready")
    assert {url.rsplit(":", 1)[-1] for url in urls[1:7]} == {"18001/ready", "18001/health"}
    assert all(url.rsplit(":", 1)[-1] in {"13001/login", "13001/presentation"} for url in urls[7:])
    assert "option httpchk GET /ready" in slotctl.proxy_config("backend", "blue")
    assert "option httpchk GET /login" in slotctl.proxy_config("frontend", "blue")


def test_backend_stage_passes_release_identity_to_process():
    with patch.object(slotctl, "validate_backend_connection_budget"), \
         patch.object(slotctl, "inspect_image"), \
         patch.object(slotctl, "remove_inactive_container"), \
         patch.object(slotctl, "run") as run, \
         patch.object(slotctl, "wait_for_health"), \
         patch.object(slotctl, "warm"):
        slotctl.stage("backend", "blue", "20261027_120000", "backend-image")

    command = run.call_args.args
    index = command.index("RELEASE_ID=20261027_120000")
    assert command[index - 1:index + 1] == ("-e", "RELEASE_ID=20261027_120000")
