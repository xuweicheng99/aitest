from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "agent_mode": "mock" if settings.mock_mode or not settings.api_key else "llm",
        "model": settings.model,
    }

