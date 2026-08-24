from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.agent import AgentStep


class RunRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)
    goal: str = Field(..., min_length=3, max_length=4000)
    headless: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("测试目标不能为空")
        return value


class ArtifactLinks(BaseModel):
    screenshot: str | None = None
    trace: str | None = None


class ExecutionResult(BaseModel):
    status: Literal["passed", "failed"]
    error: str | None = None
    url: str
    final_url: str
    title: str
    duration_ms: int
    console: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    artifact_errors: list[str] = Field(default_factory=list)
    agent_steps: list[AgentStep] = Field(default_factory=list)
    step_count: int = 0
    artifacts: ArtifactLinks
    started_at: str | None = None
    finished_at: str | None = None


class RunResponse(BaseModel):
    run_id: str
    mode: Literal["mock", "llm"]
    generated_code: str
    result: ExecutionResult


class RunRecord(BaseModel):
    run_id: str
    url: str
    goal: str
    headless: bool | None
    status: Literal["running", "passed", "failed", "error"]
    mode: Literal["mock", "llm"] | None = None
    generated_code: str | None = None
    result: ExecutionResult | None = None
    error: str | None = None
    started_at: str
    finished_at: str | None = None


class RunSummary(BaseModel):
    run_id: str
    url: str
    goal: str
    status: Literal["running", "passed", "failed", "error"]
    mode: Literal["mock", "llm"] | None = None
    started_at: str
    finished_at: str | None = None
