from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.run_service import RunService


@lru_cache
def get_run_service() -> RunService:
    return RunService(get_settings())

