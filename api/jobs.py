"""JobRegistry — in-process job state machine for csm-set API.

Per-kind FIFO queues with dedicated async worker tasks.  One worker per
JobKind guarantees at most one job of each kind runs at a time, while
different kinds can execute concurrently.

Persistence is an atomic JSON write (temp file + rename) under
``results/.tmp/jobs/``.  On lifespan startup, ``load_all()`` rehydrates
the registry so completed jobs survive restarts.  Any job left in
RUNNING state from a previous process is marked FAILED during reload.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ulid import ULID

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    DATA_REFRESH = "data_refresh"
    BACKTEST_RUN = "backtest_run"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class JobRecord(BaseModel):
    """Immutable snapshot of a single job's lifecycle."""

    job_id: str
    kind: JobKind
    status: JobStatus
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class JobRegistry:
    """In-process job state machine with WAL-style JSON persistence.

    Each :class:`JobKind` gets its own :class:`asyncio.Queue` and a
    long-running worker task that drains jobs sequentially.  Different
    kinds run concurrently; same-kind jobs are strictly FIFO.

    Persistence is atomic: each state change writes to a ``.tmp`` file
    that is atomically renamed over the ``.json`` target so a crash
    mid-write never leaves a corrupted record.

    Parameters:
        persistence_dir: Directory for per-job JSON files.
    """

    def __init__(self, persistence_dir: Path) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._persistence_dir = persistence_dir
        self._persistence_dir.mkdir(parents=True, exist_ok=True)

        # Per-kind FIFO queues — items are (JobRecord, runner, kwargs).
        self._queues: dict[JobKind, asyncio.Queue[tuple[JobRecord, Any, dict[str, Any]]]] = {
            kind: asyncio.Queue() for kind in JobKind
        }

        # Worker tasks — created lazily on first submit per kind.
        self._workers: dict[JobKind, asyncio.Task[None] | None] = {kind: None for kind in JobKind}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> JobRecord | None:
        """Return the job record for *job_id*, or *None*."""
        return self._jobs.get(job_id)

    def list(
        self,
        kind: JobKind | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        """Return filtered job records, newest first."""
        results: list[JobRecord] = []
        for record in reversed(list(self._jobs.values())):
            if kind is not None and record.kind != kind:
                continue
            if status is not None and record.status != status:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    async def submit(
        self,
        kind: JobKind,
        runner: Any,
        *,
        request_id: str | None = None,
        **kwargs: Any,
    ) -> JobRecord:
        """Enqueue a new job and return its ACCEPTED record immediately.

        Args:
            kind: The job category (shapes concurrency).
            runner: An ``async def`` callable that returns ``dict[str, Any]``.
            request_id: Optional request identifier for log correlation.
            **kwargs: Forwarded to *runner* when the job starts.

        Returns:
            The newly created :class:`JobRecord` in ACCEPTED status.
        """
        job_id: str = str(ULID())
        record = JobRecord(
            job_id=job_id,
            kind=kind,
            status=JobStatus.ACCEPTED,
            request_id=request_id,
        )
        self._jobs[job_id] = record
        self._persist(record)

        await self._queues[kind].put((record, runner, kwargs))
        self._ensure_worker(kind)

        logger.info("Job %s (%s) accepted", job_id, kind.value)
        return record

    def cancel(self, job_id: str) -> bool:
        """Cancel a job that is still ACCEPTED.

        Returns:
            *True* if the job was cancelled, *False* if it was not found
            or is no longer in ACCEPTED state.
        """
        record = self._jobs.get(job_id)
        if record is None or record.status is not JobStatus.ACCEPTED:
            return False
        record.status = JobStatus.CANCELLED
        record.finished_at = datetime.now(UTC)
        self._persist(record)
        logger.info("Job %s cancelled", job_id)
        return True

    async def shutdown(self) -> None:
        """Cancel all worker tasks and wait for them to finish.

        Safe to call multiple times.  After shutdown the registry is
        still readable via :meth:`get` and :meth:`list`.
        """
        for _kind, task in self._workers.items():
            if task is not None and not task.done():
                task.cancel()
        for _kind, task in self._workers.items():
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def load_all(cls, persistence_dir: Path) -> JobRegistry:
        """Rehydrate a registry from every ``*.json`` file on disk.

        Jobs left in RUNNING state (process died mid-execution) are
        marked FAILED with an appropriate error message.
        """
        registry = cls(persistence_dir)
        if not persistence_dir.is_dir():
            return registry

        for path in sorted(persistence_dir.glob("*.json")):
            try:
                record = JobRecord.model_validate_json(path.read_text())
            except Exception:
                logger.warning("Skipping unparseable job file %s", path)
                continue

            # Any job still RUNNING from a previous process is orphaned.
            if record.status is JobStatus.RUNNING:
                record.status = JobStatus.FAILED
                record.finished_at = datetime.now(UTC)
                record.error = "Process terminated before job completed"
                registry._persist(record)
                logger.warning("Marked orphaned job %s as FAILED", record.job_id)

            registry._jobs[record.job_id] = record

        logger.info("Loaded %d job record(s) from %s", len(registry._jobs), persistence_dir)
        return registry

    def _persist(self, record: JobRecord) -> None:
        """Atomically write *record* to ``{persistence_dir}/{job_id}.json``."""
        path = self._persistence_dir / f"{record.job_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        tmp.rename(path)

    # ------------------------------------------------------------------
    # Internal — worker lifecycle
    # ------------------------------------------------------------------

    def _ensure_worker(self, kind: JobKind) -> None:
        """Start the per-kind worker task if it is not already running."""
        task = self._workers[kind]
        if task is None or task.done():
            self._workers[kind] = asyncio.create_task(self._kind_worker(kind))

    async def _kind_worker(self, kind: JobKind) -> None:
        """Drain the *kind* queue sequentially until cancelled."""
        queue = self._queues[kind]
        while True:
            record, runner, kwargs = await queue.get()
            if record.status is JobStatus.CANCELLED:
                queue.task_done()
                continue

            # Transition ACCEPTED → RUNNING
            record.status = JobStatus.RUNNING
            record.started_at = datetime.now(UTC)
            self._persist(record)
            logger.info("Job %s (%s) started", record.job_id, kind.value)

            try:
                summary: dict[str, Any] = await runner(**kwargs)
            except Exception as exc:
                record.status = JobStatus.FAILED
                record.error = str(exc)
                record.finished_at = datetime.now(UTC)
                self._persist(record)
                logger.exception("Job %s (%s) failed", record.job_id, kind.value)
            else:
                record.status = JobStatus.SUCCEEDED
                record.summary = summary
                record.finished_at = datetime.now(UTC)
                self._persist(record)
                logger.info("Job %s (%s) succeeded", record.job_id, kind.value)

            queue.task_done()


__all__: list[str] = ["JobKind", "JobRecord", "JobRegistry", "JobStatus"]
