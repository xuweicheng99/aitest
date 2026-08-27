from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数") from exc
    if parsed < minimum:
        raise ValueError(f"环境变量 {name} 不能小于 {minimum}")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    public_dir: Path
    runs_dir: Path
    browsers_path: Path
    api_key: str
    base_url: str
    model: str
    mock_mode: bool
    json_response_mode: bool
    headless: bool
    ignore_https_errors: bool
    model_timeout_seconds: int
    test_timeout_seconds: int
    max_concurrent_runs: int
    console_log_limit: int
    agent_max_steps: int
    agent_max_consecutive_failures: int
    agent_action_timeout_ms: int
    agent_navigation_timeout_ms: int
    agent_observation_chars: int
    agent_dom_chars: int
    agent_observation_delay_ms: int
    agent_include_screenshot: bool
    agent_history_limit: int
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    runs_value = Path(os.getenv("RUNS_DIR", "runs"))
    runs_dir = runs_value if runs_value.is_absolute() else PROJECT_ROOT / runs_value
    default_browsers = Path(tempfile.gettempdir()) / "ai-playwright-browsers"
    browsers_path = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH", str(default_browsers)))
    origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
        if origin.strip()
    )
    return Settings(
        project_root=PROJECT_ROOT,
        public_dir=PROJECT_ROOT / "public",
        runs_dir=runs_dir,
        browsers_path=browsers_path,
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        mock_mode=_as_bool("MOCK_MODE", True),
        json_response_mode=_as_bool("OPENAI_JSON_RESPONSE_MODE", True),
        headless=_as_bool("PLAYWRIGHT_HEADLESS", True),
        ignore_https_errors=_as_bool("PLAYWRIGHT_IGNORE_HTTPS_ERRORS", False),
        model_timeout_seconds=_as_int("MODEL_TIMEOUT_SECONDS", 90),
        test_timeout_seconds=_as_int("TEST_TIMEOUT_SECONDS", 180),
        max_concurrent_runs=_as_int("MAX_CONCURRENT_RUNS", 2),
        console_log_limit=_as_int("CONSOLE_LOG_LIMIT", 100),
        agent_max_steps=_as_int("AGENT_MAX_STEPS", 12),
        agent_max_consecutive_failures=_as_int("AGENT_MAX_CONSECUTIVE_FAILURES", 3),
        agent_action_timeout_ms=_as_int("AGENT_ACTION_TIMEOUT_MS", 10_000, 100),
        agent_navigation_timeout_ms=_as_int("AGENT_NAVIGATION_TIMEOUT_MS", 30_000, 1000),
        agent_observation_chars=_as_int("AGENT_OBSERVATION_CHARS", 12_000, 1000),
        agent_dom_chars=_as_int("AGENT_DOM_CHARS", 12_000, 1000),
        agent_observation_delay_ms=_as_int("AGENT_OBSERVATION_DELAY_MS", 250),
        agent_include_screenshot=_as_bool("AGENT_INCLUDE_SCREENSHOT", True),
        agent_history_limit=_as_int("AGENT_HISTORY_LIMIT", 8),
        cors_origins=origins,
    )
