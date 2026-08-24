import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.schemas.agent import AgentDecision, LocatorTarget, PageObservation
from app.services.browser_action_service import ActionExecution, BrowserActionService
from app.services.playwright_service import PlaywrightService


class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"

    async def goto(self, url: str, **_kwargs) -> None:
        self.url = url.rstrip("/") + "/"


class FakeObserver:
    async def observe(self, page: FakePage) -> PageObservation:
        return PageObservation(
            url=page.url,
            title="Test App",
            aria_snapshot='- button "提交"',
            interactive_elements=[{"tag": "button", "text": "提交"}],
        )


class FakeActions:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _page: FakePage, decision: AgentDecision) -> ActionExecution:
        self.calls += 1
        if self.calls == 1:
            return ActionExecution(False, self.render_code(decision), "元素不存在")
        return ActionExecution(True, self.render_code(decision))

    @staticmethod
    def render_code(decision: AgentDecision) -> str:
        return BrowserActionService.render_code(decision)


class CorrectingAgent:
    mode = "llm"

    def __init__(self) -> None:
        self.seen_errors: list[str | None] = []

    async def decide(self, **kwargs) -> AgentDecision:
        self.seen_errors.append(kwargs["last_error"])
        step = kwargs["step_number"]
        if step == 1:
            return AgentDecision(
                action="click",
                target=LocatorTarget(strategy="text", value="错误按钮"),
            )
        if step == 2:
            return AgentDecision(
                action="click",
                target=LocatorTarget(strategy="role", role="button", value="提交"),
            )
        if step == 3:
            return AgentDecision(
                action="assert_visible",
                target=LocatorTarget(strategy="role", role="button", value="提交"),
            )
        return AgentDecision(action="finish", message="目标已验证")


def test_agent_reobserves_and_corrects_failed_action(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        browsers_path=tmp_path,
        agent_action_timeout_ms=1000,
        agent_max_steps=6,
        agent_max_consecutive_failures=3,
    )
    service = PlaywrightService(settings)
    service.observer = FakeObserver()
    service.actions = FakeActions()
    agent = CorrectingAgent()

    result = asyncio.run(
        service._run_agent_loop(
            page=FakePage(),
            url="https://example.com",
            goal="点击提交并验证按钮",
            agent=agent,
        )
    )

    assert result.status == "passed"
    assert len(result.steps) == 4
    assert result.steps[0].success is False
    assert result.steps[1].success is True
    assert agent.seen_errors[1] == "元素不存在"
    assert result.steps[-1].action.action == "finish"
