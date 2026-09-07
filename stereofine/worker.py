from __future__ import annotations

import queue
import threading
import traceback
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class WorkerMessageKind(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    RESULT = "result"
    CANCELLED = "cancelled"
    ERROR = "error"


class JobCancelled(RuntimeError):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled("Job wurde abgebrochen.")


@dataclass(frozen=True)
class WorkerMessage:
    job_id: str
    kind: WorkerMessageKind
    payload: Any = None


@dataclass
class WorkerJob(Generic[T]):
    job_id: str
    token: CancellationToken
    thread: threading.Thread


class WorkerManager:
    """GUI-agnostic worker helper. Tk widgets are never touched from worker threads."""

    def __init__(self) -> None:
        self.messages: queue.Queue[WorkerMessage] = queue.Queue()
        self._jobs: dict[str, WorkerJob[Any]] = {}
        self._lock = threading.Lock()

    def start(
        self,
        function: Callable[[CancellationToken, Callable[[Any], None]], T],
        *,
        name: str = "StereoFineWorker",
    ) -> WorkerJob[T]:
        job_id = uuid.uuid4().hex
        token = CancellationToken()

        def progress(payload: Any) -> None:
            self.messages.put(WorkerMessage(job_id, WorkerMessageKind.PROGRESS, payload))

        def runner() -> None:
            self.messages.put(WorkerMessage(job_id, WorkerMessageKind.STARTED))
            try:
                result = function(token, progress)
                if token.cancelled:
                    self.messages.put(WorkerMessage(job_id, WorkerMessageKind.CANCELLED))
                else:
                    self.messages.put(WorkerMessage(job_id, WorkerMessageKind.RESULT, result))
            except JobCancelled:
                self.messages.put(WorkerMessage(job_id, WorkerMessageKind.CANCELLED))
            except Exception as exc:
                self.messages.put(
                    WorkerMessage(
                        job_id,
                        WorkerMessageKind.ERROR,
                        {"exception": exc, "traceback": traceback.format_exc()},
                    )
                )
            finally:
                with self._lock:
                    self._jobs.pop(job_id, None)

        thread = threading.Thread(target=runner, name=f"{name}-{job_id[:8]}", daemon=True)
        job: WorkerJob[T] = WorkerJob(job_id=job_id, token=token, thread=thread)
        with self._lock:
            self._jobs[job_id] = job
        thread.start()
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        job.token.cancel()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.token.cancel()

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._jobs
