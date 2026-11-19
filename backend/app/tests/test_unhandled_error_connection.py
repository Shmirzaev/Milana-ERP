"""A handled 500 must not return a doomed Uvicorn socket to a proxy pool."""
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import _unhandled_exception


def test_unhandled_error_closes_socket_before_the_next_request(tmp_path):
    # Use real Uvicorn/HTTP: TestClient cannot reproduce a proxy reusing a socket
    # between the error response and Uvicorn's subsequent connection close.
    script = """
import sys
from fastapi import FastAPI
import uvicorn
from app.main import _unhandled_exception
app = FastAPI(exception_handlers={Exception: _unhandled_exception})
@app.get('/error')
def error():
    raise RuntimeError('private-error-marker')
@app.get('/normal')
def normal():
    return {'ok': True}
uvicorn.run(app, fd=int(sys.argv[1]), log_level='error')
"""
    with socket.socket() as listener, (tmp_path / "uvicorn.log").open("w") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
        server = subprocess.Popen(
            [sys.executable, "-c", script, str(listener.fileno())],
            env=env, stdout=log, stderr=log, pass_fds=(listener.fileno(),),
        )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            deadline = time.monotonic() + 30
            while True:
                assert server.poll() is None, "Uvicorn exited before readiness"
                try:
                    connection.request("GET", "/normal")
                    response = connection.getresponse()
                    response.read()
                    assert response.status == 200
                    break
                except (OSError, http.client.HTTPException):
                    connection.close()
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            for _ in range(5):
                connection.request("GET", "/error")
                response = connection.getresponse()
                assert response.status == 500
                assert response.read() == b'{"detail":"Internal server error"}'
                assert response.getheader("Connection") == "close"
                assert connection.sock is None
                connection.request("GET", "/normal")
                response = connection.getresponse()
                assert response.status == 200
                assert response.read() == b'{"ok":true}'
                assert response.getheader("Connection") is None
        finally:
            connection.close()
            server.terminate()
            server.wait(timeout=15)


def test_handled_refusal_does_not_close_healthy_connections():
    app = FastAPI(exception_handlers={Exception: _unhandled_exception})

    @app.get("/refused")
    def refused():
        raise HTTPException(403, "Not allowed")

    response = TestClient(app, raise_server_exceptions=False).get("/refused")
    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed"}
    assert "connection" not in response.headers
