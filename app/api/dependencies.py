from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.run_service import RunService
from app.services.test_plan_service import TestPlanService


@lru_cache
def get_run_service() -> RunService:
    return RunService(get_settings())


@lru_cache
def get_test_plan_service() -> TestPlanService:
    settings = get_settings()
    return TestPlanService(settings, get_run_service())
