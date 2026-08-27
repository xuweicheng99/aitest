from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.run import RunResponse


__test__ = False


class TestCase(BaseModel):
    case_id: str = Field(..., pattern=r"^TC-\d{3}$")
    title: str = Field(..., min_length=2, max_length=200)
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    steps: list[str] = Field(..., min_length=1, max_length=30)
    expected_results: list[str] = Field(..., min_length=1, max_length=30)
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    case_type: Literal["positive", "negative", "boundary", "permission", "state"] = "positive"
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True

    __test__ = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()

    @field_validator("preconditions", "steps", "expected_results", "source_refs")
    @classmethod
    def normalize_items(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @model_validator(mode="after")
    def require_executable_content(self) -> "TestCase":
        if not self.steps:
            raise ValueError("测试用例必须包含操作步骤")
        if not self.expected_results:
            raise ValueError("测试用例必须包含预期结果")
        return self


class TestPlan(BaseModel):
    plan_id: str = Field(..., pattern=r"^[a-f0-9]{10}$")
    name: str = Field(..., min_length=2, max_length=200)
    source_name: str = Field(..., min_length=1, max_length=255)
    requirements_summary: str = Field(..., min_length=3, max_length=4000)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    cases: list[TestCase] = Field(..., min_length=1, max_length=50)
    created_at: str

    __test__ = False


class PlanExecuteRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)
    plan: TestPlan
    headless: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return value

    @model_validator(mode="after")
    def require_enabled_case(self) -> "PlanExecuteRequest":
        if not any(case.enabled for case in self.plan.cases):
            raise ValueError("至少需要选择一条测试用例")
        return self


class CaseExecution(BaseModel):
    case_id: str
    title: str
    status: Literal["passed", "failed", "error"]
    run: RunResponse | None = None
    error: str | None = None


class PlanExecutionResponse(BaseModel):
    plan_id: str
    status: Literal["passed", "failed"]
    total: int
    passed: int
    failed: int
    duration_ms: int
    cases: list[CaseExecution]
