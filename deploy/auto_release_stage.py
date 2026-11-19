"""Narrow adapter for the reviewed installed controller; routing stays untouched."""
from __future__ import annotations


def stage(controller, role, slot, release, image):
    if role != "backend":
        return controller.stage(role, slot, release, image)
    expected = [
        "docker", "run", "-d", "--name", controller.container_name(role, slot),
        "--restart", "unless-stopped", "--label", f"milana.release={release}",
        "--label", f"milana.slot={slot}", "--label", "milana.role=backend",
        "-p", f"127.0.0.1:{controller.slot_port(role, slot)}:10000",
        "--env-file", str(controller.BASE / "shared/backend.env"),
        "-e", "DB_POOL_SIZE=8", "-e", "DB_MAX_OVERFLOW=4", "-e", "WEB_CONCURRENCY=2",
        "-v", "/app/storage:/app/storage", image,
    ]
    original = controller.run
    started = False

    def adapted(*args, **kwargs):
        nonlocal started
        if args[:2] == ("docker", "run"):
            if started or list(args) != expected:
                raise ValueError("Installed staging command differs from reviewed arguments")
            started = True
            args = (*args[:-1], "-e", f"RELEASE_ID={release}", image)
        return original(*args, **kwargs)

    controller.run = adapted
    try:
        result = controller.stage(role, slot, release, image)
        if not started:
            raise ValueError("Installed staging did not create the expected backend")
        return result
    finally:
        controller.run = original
