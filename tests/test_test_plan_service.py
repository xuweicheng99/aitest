import asyncio
from types import SimpleNamespace

from app.schemas.run import ArtifactLinks, ExecutionResult, RunResponse
from app.schemas.test_plan import PlanExecuteRequest
from app.services.test_plan_service import TestPlanService


class FakeRunService:
    def __init__(self) -> None:
        self.goals: list[str] = []

    async def run(self, request):
        self.goals.append(request.goal)
        status = "failed" if "无效" in request.goal else "passed"
        return RunResponse(
            run_id=("a" if status == "passed" else "b") * 10,
            mode="mock",
            generated_code="# test",
            result=ExecutionResult(
                status=status,
                error=None if status == "passed" else "validation missing",
                url=request.url,
                final_url=request.url,
                title="Test",
                duration_ms=1,
                artifacts=ArtifactLinks(),
            ),
        )


def make_settings():
    return SimpleNamespace(mock_mode=True, api_key="")


def test_mock_generation_returns_structured_cases() -> None:
    service = TestPlanService(make_settings(), FakeRunService())
    plan = asyncio.run(
        service.generate(
            requirements="# 登录\n用户可以使用账号和密码登录系统。",
            source_name="login.md",
            max_cases=2,
        )
    )

    assert plan.source_name == "login.md"
    assert [case.case_id for case in plan.cases] == ["TC-001", "TC-002"]
    assert plan.cases[1].case_type == "negative"


def test_execute_plan_runs_only_enabled_cases_and_summarizes() -> None:
    runner = FakeRunService()
    service = TestPlanService(make_settings(), runner)
    plan = asyncio.run(
        service.generate(
            requirements="# 登录\n用户可以使用账号和密码登录系统。",
            source_name="login.md",
            max_cases=3,
        )
    )
    plan.cases[2].enabled = False

    result = asyncio.run(
        service.execute(
            PlanExecuteRequest(url="https://example.com", plan=plan, headless=True)
        )
    )

    assert result.total == 2
    assert result.passed == 1
    assert result.failed == 1
    assert len(runner.goals) == 2
    assert "TC-001" in runner.goals[0]
    assert "至少一个明确断言" in runner.goals[0]


def test_model_case_normalization_handles_common_compatible_shapes() -> None:
    payload = {
        "name": "登录计划",
        "requirements_summary": "验证用户登录功能",
        "cases": [
            {
                "name": "错误密码",
                "precondition": "已进入登录页",
                "test_steps": "1. 输入错误密码\n2. 点击登录",
                "expected_result": "显示密码错误提示",
                "priority": "优先级P0",
                "type": "异常",
            }
        ],
    }

    plan = TestPlanService._build_plan(payload, "login.md", 5)

    assert plan.cases[0].steps == ["输入错误密码", "点击登录"]
    assert plan.cases[0].expected_results == ["显示密码错误提示"]
    assert plan.cases[0].priority == "P0"
    assert plan.cases[0].case_type == "negative"
