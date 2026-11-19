"""Exercise the generated slot router against an unavailable frontend slot."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


class SlotRouterErrorfileTest(unittest.TestCase):
    def test_frontend_page_and_api_errors(self) -> None:
        spec = importlib.util.spec_from_file_location("slotctl", ROOT / "deploy/slotctl.py")
        assert spec and spec.loader
        slotctl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(slotctl)
        (ROOT / ".codex-work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".codex-work") as directory:
            runtime = Path(directory)
            slotctl.FRONTEND_ERROR_PATH = runtime / "frontend-503.http"
            slotctl.API_ERROR_PATH = runtime / "api-503.http"
            slotctl.ROLES = {**slotctl.ROLES, "frontend": {"stable": 3000, "blue": 13001, "green": 13002, "health": "/login"}}
            slotctl.write_errorfiles()
            config = slotctl.proxy_config("frontend", "blue")
            # The generated paths are remapped into the disposable router container.
            config = config.replace(str(runtime), "/cfg")
            (runtime / "haproxy.cfg").write_text(config)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            name = f"milana-slot-errorfile-test-{port}"
            subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:3000", "-v", f"{runtime}:/cfg:ro", "haproxy:3.1-alpine", "haproxy", "-W", "-db", "-f", "/cfg/haproxy.cfg"], check=True, capture_output=True)
            try:
                def failed(path: str) -> tuple[str, str, int]:
                    for _ in range(30):
                        try:
                            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2)
                        except urllib.error.HTTPError as exc:
                            with exc:
                                return exc.headers.get_content_type(), exc.read().decode(), exc.code
                        except OSError:
                            time.sleep(0.1)
                    logs = subprocess.run(["docker", "logs", name], text=True, capture_output=True)
                    raise AssertionError(f"router did not return an error for {path}: {logs.stdout} {logs.stderr}")

                page_type, page, status = failed("/login")
                self.assertEqual((status, page_type), (503, "text/html"))
                self.assertIn("Back in a moment", page)
                self.assertIn('content="10"', page)
                self.assertIn('lang="ru"', page)
                self.assertIn('lang="uz"', page)
                api_type, api, status = failed("/api/auth/me")
                self.assertEqual((status, api_type), (503, "application/json"))
                self.assertEqual(api.strip(), '{"detail":"Service unavailable"}')
            finally:
                subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)


if __name__ == "__main__":
    unittest.main()
