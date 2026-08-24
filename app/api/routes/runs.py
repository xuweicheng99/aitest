from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.api.dependencies import get_run_service
from app.schemas.run import RunRecord, RunRequest, RunResponse, RunSummary
from app.services.run_service import RunService


router = APIRouter(prefix="/runs", tags=["test runs"])


@router.post("", response_model=RunResponse)
@router.post("/", response_model=RunResponse, include_in_schema=False)
async def run_test(
    request: RunRequest,
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    return await service.run(request)


@router.get("", response_model=list[RunSummary])
@router.get("/", response_model=list[RunSummary], include_in_schema=False)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    service: RunService = Depends(get_run_service),
) -> list[RunSummary]:
    return service.list_runs(limit)


@router.get("/{run_id}", response_model=RunRecord)
def get_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> RunRecord:
    return service.get_run(run_id)


@router.get("/{run_id}/{artifact}", response_class=FileResponse)
def get_artifact(
    run_id: str,
    artifact: str,
    service: RunService = Depends(get_run_service),
) -> FileResponse:
    return FileResponse(service.repository.artifact_path(run_id, artifact))

