from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.core.config import Settings
from app.repositories.run_repository import RunRepository
from app.schemas.run import RunRecord, RunRequest, RunResponse, RunSummary
from app.services.agent_service import AgentService
from app.services.playwright_service import PlaywrightService


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunService:
    def __init__(self, settings: Settings) -> None:
        self.repository = RunRepository(settings.runs_dir)
        self.agent = AgentService(settings)
        self.playwright = PlaywrightService(settings)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)

    async def run(self, request: RunRequest) -> RunResponse:
        run_id = uuid.uuid4().hex[:10]
        run_dir = self.repository.create_directory(run_id)
        record = RunRecord(
            run_id=run_id,
            url=request.url,
            goal=request.goal,
            headless=request.headless,
            status="running",
            started_at=utc_now(),
        )
        self.repository.save(record)

        try:
            async with self._semaphore:
                result, generated_code = await self.playwright.execute(
                    url=request.url,
                    goal=request.goal,
                    agent=self.agent,
                    run_dir=run_dir,
                    headless=request.headless,
                )
            result.started_at = record.started_at
            result.finished_at = utc_now()
            record.mode = self.agent.mode
            record.generated_code = generated_code
            record.result = result
            record.status = result.status
            record.finished_at = result.finished_at
            self.repository.save(record)
            return RunResponse(
                run_id=run_id,
                mode=self.agent.mode,
                generated_code=generated_code,
                result=result,
            )
        except Exception as exc:
            record.status = "error"
            record.error = str(exc) or exc.__class__.__name__
            record.finished_at = utc_now()
            self.repository.save(record)
            self.repository.save_error_text(run_id, record.error)
            raise

    def list_runs(self, limit: int) -> list[RunSummary]:
        return self.repository.list(limit)

    def get_run(self, run_id: str) -> RunRecord:
        return self.repository.get(run_id)
