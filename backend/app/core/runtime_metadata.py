"""Keep the worker's startup metadata out of recurring cyclic-GC scans."""

from __future__ import annotations

from contextlib import contextmanager
import gc
import logging
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("milana")


@contextmanager
def startup_metadata(app: FastAPI, *, enabled: bool) -> Iterator[None]:
    """Own one freeze for a strict worker, and thaw it on lifespan exit.

    OpenAPI prepares FastAPI's lazy route/dependency metadata without invoking
    requests or dependencies. Collect before freezing that long-lived graph.
    New request objects still use automatic GC with its existing thresholds.
    Frozen cycles can remain until shutdown, so this is worker-lifetime policy;
    it must not take ownership of another component's disabled or frozen GC.
    """
    if not enabled or not gc.isenabled() or gc.get_freeze_count():
        yield
        return

    app.openapi()
    gc.collect()
    gc.freeze()
    try:
        log.info("startup: prepared route metadata; frozen objects=%s", gc.get_freeze_count())
        yield
    finally:
        gc.unfreeze()
