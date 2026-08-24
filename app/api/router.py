from fastapi import APIRouter, Depends

from app.api.dependencies import get_run_service
from app.api.routes import health, runs
from app.schemas.run import RunRequest, RunResponse
from app.services.run_service import RunService


api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(runs.router)


@api_router.post("/run", response_model=RunResponse, include_in_schema=False)
async def legacy_run_test(
    request: RunRequest,
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    """Keep the original frontend endpoint compatible with version 0.1."""
    return await service.run(request)
