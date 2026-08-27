from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.core.exceptions import ModelProviderError
from app.schemas.run import RunRequest
from app.schemas.test_plan import (
    CaseExecution,
    PlanExecuteRequest,
    PlanExecutionResponse,
    TestCase,
    TestPlan,
)
from app.services.agent_service import AgentService
from app.services.run_service import RunService


__test__ = False


PLAN_SYSTEM_PROMPT = """You are a senior software test analyst. Convert the supplied
requirements document into executable web functional test cases. Return one JSON object
only. Cover the most important positive, negative, boundary, permission, and state
scenarios that are supported by the document. Do not invent credentials, URLs, business
rules, or acceptance criteria. Put missing execution information in assumptions.

Each case must be independent, concise, and observable in a browser. Steps describe user
actions. Expected results describe verifiable URL, title, visible text, element state, or
page behavior. source_refs quote short section names or requirement phrases.

When the input is a broad feature goal rather than a full requirements document, decompose
that feature into distinct data-driven scenarios. Include a successful happy path when the
required valid test data is supplied, plus representative invalid input, empty required
fields, boundary values, permissions, and relevant state transitions. Do not create several
cases that merely repeat the same steps and expectation. Never invent valid accounts,
passwords, verification codes, or business rules; record missing data in assumptions and
make affected preconditions explicit.

Response schema:
{"name":"plan name","requirements_summary":"summary","assumptions":["missing fact"],
"cases":[{"title":"case title","preconditions":["condition"],"steps":["action"],
"expected_results":["observable result"],"priority":"P0|P1|P2|P3",
"case_type":"positive|negative|boundary|permission|state","source_refs":["reference"]}]}
"""


class TestPlanService:
    __test__ = False

    def __init__(self, settings: Settings, run_service: RunService) -> None:
        self.settings = settings
        self.run_service = run_service

    async def generate(
        self,
        *,
        requirements: str,
        source_name: str,
        max_cases: int,
    ) -> TestPlan:
        if self.settings.mock_mode or not self.settings.api_key:
            payload = self._mock_plan(requirements, source_name, max_cases)
        else:
            payload = await self._generate_with_model(requirements, max_cases)
        return self._build_plan(payload, source_name, max_cases)

    async def execute(self, request: PlanExecuteRequest) -> PlanExecutionResponse:
        started = time.perf_counter()
        results: list[CaseExecution] = []
        for case in request.plan.cases:
            if not case.enabled:
                continue
            try:
                run = await self.run_service.run(
                    RunRequest(
                        url=request.url,
                        goal=self._execution_goal(case),
                        headless=request.headless,
                    )
                )
                results.append(
                    CaseExecution(
                        case_id=case.case_id,
                        title=case.title,
                        status=run.result.status,
                        run=run,
                        error=run.result.error,
                    )
                )
            except Exception as exc:
                results.append(
                    CaseExecution(
                        case_id=case.case_id,
                        title=case.title,
                        status="error",
                        error=str(exc) or exc.__class__.__name__,
                    )
                )

        passed = sum(item.status == "passed" for item in results)
        failed = len(results) - passed
        return PlanExecutionResponse(
            plan_id=request.plan.plan_id,
            status="passed" if failed == 0 else "failed",
            total=len(results),
            passed=passed,
            failed=failed,
            duration_ms=int((time.perf_counter() - started) * 1000),
            cases=results,
        )

    async def _generate_with_model(self, requirements: str, max_cases: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "maximum_cases": max_cases,
                            "requirements_document": requirements,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        if self.settings.json_response_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.model_timeout_seconds) as client:
                response = await client.post(
                    f"{self.settings.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return AgentService._parse_json(content)
        except httpx.TimeoutException as exc:
            raise ModelProviderError("生成测试用例时大模型请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(
                f"生成测试用例时模型服务返回 HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelProviderError("大模型未返回有效的测试计划") from exc

    @staticmethod
    def _build_plan(payload: dict[str, Any], source_name: str, max_cases: int) -> TestPlan:
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ModelProviderError("大模型未生成任何测试用例")
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        # Do not trust the model to make titles unique: two differently named cases
        # with identical preconditions/actions/expectations are the same executable
        # scenario and must not be run twice.
        for raw_case in raw_cases:
            if not isinstance(raw_case, dict):
                continue
            candidate = TestPlanService._normalize_case(raw_case, len(normalized) + 1)
            signature = TestPlanService._case_signature(candidate)
            if signature in seen:
                continue
            seen.add(signature)
            normalized.append(candidate)
            if len(normalized) >= max_cases:
                break
        if not normalized:
            raise ModelProviderError("大模型未生成有效的测试用例")
        # Re-number after duplicate removal so IDs are contiguous and stable.
        for index, case in enumerate(normalized, start=1):
            case["case_id"] = f"TC-{index:03d}"
        try:
            cases = TypeAdapter(list[TestCase]).validate_python(normalized)
            return TestPlan(
                plan_id=uuid.uuid4().hex[:10],
                name=str(payload.get("name") or "Web 需求测试计划").strip(),
                source_name=source_name,
                requirements_summary=str(payload.get("requirements_summary") or "需求功能测试").strip(),
                assumptions=TestPlanService._string_list(payload.get("assumptions")),
                cases=cases,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        except ValidationError as exc:
            first_error = exc.errors()[0]
            location = ".".join(str(item) for item in first_error.get("loc", ()))
            raise ModelProviderError(
                f"大模型生成的用例格式无效（{location}）：{first_error['msg']}"
            ) from exc

    @staticmethod
    def _normalize_case(raw: dict[str, Any], index: int) -> dict[str, Any]:
        priority = str(raw.get("priority") or "P1").upper().replace("优先级", "").strip()
        if priority not in {"P0", "P1", "P2", "P3"}:
            priority = "P1"
        raw_type = str(raw.get("case_type") or raw.get("type") or "positive").lower().strip()
        type_aliases = {
            "positive": "positive",
            "functional": "positive",
            "happy_path": "positive",
            "正向": "positive",
            "功能": "positive",
            "negative": "negative",
            "反向": "negative",
            "异常": "negative",
            "boundary": "boundary",
            "边界": "boundary",
            "permission": "permission",
            "security": "permission",
            "权限": "permission",
            "state": "state",
            "state_transition": "state",
            "状态": "state",
        }
        return {
            "case_id": f"TC-{index:03d}",
            "title": str(raw.get("title") or raw.get("name") or f"测试用例 {index}").strip(),
            "preconditions": TestPlanService._coerce_items(
                raw.get("preconditions", raw.get("precondition", []))
            ),
            "steps": TestPlanService._coerce_items(
                raw.get("steps", raw.get("test_steps", []))
            ),
            "expected_results": TestPlanService._coerce_items(
                raw.get("expected_results", raw.get("expected_result", raw.get("expected", [])))
            ),
            "priority": priority,
            "case_type": type_aliases.get(raw_type, "positive"),
            "source_refs": TestPlanService._coerce_items(
                raw.get("source_refs", raw.get("references", []))
            ),
            "enabled": bool(raw.get("enabled", True)),
        }

    @staticmethod
    def _case_signature(case: dict[str, Any]) -> tuple[Any, ...]:
        """Return a canonical executable signature for duplicate detection."""

        def canonical(items: object) -> tuple[str, ...]:
            if not isinstance(items, list):
                return ()
            return tuple(re.sub(r"\s+", " ", str(item)).strip().casefold() for item in items)

        return (
            canonical(case.get("preconditions")),
            canonical(case.get("steps")),
            canonical(case.get("expected_results")),
        )

    @staticmethod
    def _coerce_items(value: object) -> list[str]:
        if isinstance(value, str):
            values = re.split(r"\n+|[;；]+", value)
        elif isinstance(value, list):
            values = value
        else:
            return []
        items: list[str] = []
        for item in values:
            if isinstance(item, dict):
                item = item.get("description") or item.get("action") or item.get("text") or ""
            text = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", str(item)).strip()
            if text:
                items.append(text)
        return items

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:30]

    @staticmethod
    def _execution_goal(case: TestCase) -> str:
        preconditions = "；".join(case.preconditions) or "无特殊前置条件"
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(case.steps, 1))
        expected = "\n".join(f"- {item}" for item in case.expected_results)
        return (
            f"执行测试用例 {case.case_id}：{case.title}\n"
            f"前置条件：{preconditions}\n操作步骤：\n{steps}\n"
            f"预期结果：\n{expected}\n"
            "必须在完成操作后通过 URL、标题、可见文本或元素状态执行至少一个明确断言。"
        )

    @staticmethod
    def _mock_plan(requirements: str, source_name: str, max_cases: int) -> dict[str, Any]:
        heading = next(
            (line.strip("# ") for line in requirements.splitlines() if line.strip()),
            source_name,
        )[:100]
        candidates = [
            {
                "title": f"验证{heading}的主要流程",
                "preconditions": ["测试环境可用，已准备有效测试数据"],
                "steps": ["打开功能页面", "按需求完成主要用户操作"],
                "expected_results": ["主要流程完成且页面显示预期结果"],
                "priority": "P0",
                "case_type": "positive",
                "source_refs": [heading],
            },
            {
                "title": f"验证{heading}的必填与无效输入",
                "preconditions": ["已进入相关功能页面"],
                "steps": ["留空必填项或输入无效数据", "提交表单"],
                "expected_results": ["页面拒绝提交并显示明确校验信息"],
                "priority": "P1",
                "case_type": "negative",
                "source_refs": [heading],
            },
            {
                "title": f"验证{heading}的输入边界",
                "preconditions": ["已进入相关功能页面"],
                "steps": ["对可输入字段使用需求允许的边界值", "提交表单"],
                "expected_results": ["系统按需求处理边界值且页面无异常"],
                "priority": "P2",
                "case_type": "boundary",
                "source_refs": [heading],
            },
        ]
        return {
            "name": f"{heading} - 测试计划",
            "requirements_summary": requirements[:500],
            "assumptions": ["需要提供可访问的测试 URL 和必要的测试数据"],
            "cases": candidates[:max_cases],
        }
