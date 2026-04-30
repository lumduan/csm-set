"""JobRegistry — in-process job state machine for csm-set API.

Full implementation in Phase 5.4.  Phase 5.1 supplies the skeleton so the
lifespan can instantiate the singleton and deps.py can provide it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    DATA_REFRESH = "data_refresh"
    BACKTEST_RUN = "backtest_run"


class JobRecord(BaseModel):
    job_id: str
    kind: JobKind
    status: JobStatus
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    request_id: str | None = None


class JobRegistry:
    """In-process job state machine.

    Full implementation (submit via runner callables, asyncio.Semaphore
    concurrency, WAL persistence) lands in Phase 5.4.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list(
        self,
        kind: JobKind | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        results: list[JobRecord] = []
        for record in self._jobs.values():
            if kind is not None and record.kind != kind:
                continue
            if status is not None and record.status != status:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def submit(self, *args: Any, **kwargs: Any) -> JobRecord:
        raise NotImplementedError("JobRegistry.submit is a stub — full implementation in Phase 5.4")


__all__: list[str] = ["JobKind", "JobRecord", "JobRegistry", "JobStatus"]
