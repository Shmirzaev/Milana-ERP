"""Bounded lifecycle ownership for the two Catalog CREATE test workers."""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from threading import Barrier, Thread, current_thread
from time import monotonic
from typing import Callable, Generic, NoReturn, TypeVar

from sqlalchemy.orm import Session, sessionmaker

from app.tests.pg_approved_instance import _park


Actor = TypeVar('Actor')


class Stage(str, Enum):
    PENDING = 'pending'
    SESSION = 'session'
    PREPARE = 'prepare'
    BARRIER = 'barrier'
    ACTION = 'action'
    CLOSE = 'close'
    CLOSED = 'closed'


@dataclass
class Worker:
    thread: Thread | None = None
    session: Session | None = None
    stage: Stage = Stage.PENDING
    errors: list[BaseException] = field(default_factory=list)


@dataclass
class Owner(Generic[Actor]):
    sessions: sessionmaker[Session]
    prepare: Callable[[Session], Actor]
    action: Callable[[Session, Actor], int]
    barrier: Barrier
    workers: list[Worker]
    pool: ThreadPoolExecutor | None = None
    futures: list[Future[int]] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)


def _hold(operation: str, owner: Owner[Actor], error: BaseException) -> NoReturn:
    owner.errors.append(error)
    _park(operation, (owner,), owner.errors)
    raise RuntimeError('HOLD observer unexpectedly returned')


def _worker(owner: Owner[Actor], worker: Worker) -> int:
    worker.thread = current_thread()
    try:
        worker.stage = Stage.SESSION
        worker.session = owner.sessions()
        worker.stage = Stage.PREPARE
        actor = owner.prepare(worker.session)
        worker.stage = Stage.BARRIER
        owner.barrier.wait()
        worker.stage = Stage.ACTION
        result = owner.action(worker.session, actor)
        worker.stage = Stage.CLOSE
        worker.session.close()
        worker.stage = Stage.CLOSED
        return result
    except BaseException as error:
        worker.errors.append(error)
        _hold('CATALOG_CREATE_WORKER', owner, error)


def run_catalog_create_pair(
    sessions: sessionmaker[Session],
    prepare: Callable[[Session], Actor],
    action: Callable[[Session, Actor], int],
    *, timeout: float = 15,
) -> list[int]:
    """Return ordered results only after both sessions and exact threads finish."""
    deadline = monotonic() + timeout
    owner = Owner(sessions, prepare, action, Barrier(2, timeout=min(15, timeout)), [Worker(), Worker()])
    try:
        owner.pool = ThreadPoolExecutor(max_workers=2)
        for worker in owner.workers:
            owner.futures.append(owner.pool.submit(_worker, owner, worker))
        results = []
        for future in owner.futures:
            results.append(future.result(timeout=max(0, deadline - monotonic())))
        owner.pool.shutdown(wait=False, cancel_futures=False)
        for worker in owner.workers:
            if worker.thread is None or worker.stage != Stage.CLOSED:
                raise RuntimeError('worker completion ownership is unknown')
            worker.thread.join(timeout=max(0, deadline - monotonic()))
            if worker.thread.is_alive():
                raise TimeoutError('catalog worker thread did not terminate')
        return results
    except BaseException as error:
        _hold('CATALOG_CREATE_MAIN', owner, error)
