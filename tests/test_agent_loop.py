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

    @staticmethod
    async def navigate(page: FakePage, url: str) -> None:
        await page.goto(url)

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


class RepeatingAgent:
    mode = "llm"

    async def decide(self, **_kwargs) -> AgentDecision:
        return AgentDecision(
            action="click",
            target=LocatorTarget(strategy="text", value="不存在"),
            message="再试一次",
        )


class RepeatingSuccessfulAssertionAgent:
    mode = "llm"

    async def decide(self, **_kwargs) -> AgentDecision:
        return AgentDecision(
            action="assert_title",
            expected="Test App",
            match="exact",
        )


def test_agent_auto_finishes_after_repeated_successful_assertion(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        browsers_path=tmp_path,
        agent_action_timeout_ms=1000,
        agent_max_steps=5,
        agent_max_consecutive_failures=3,
    )
    service = PlaywrightService(settings)
    service.observer = FakeObserver()

    class SuccessfulAssertionActions(FakeActions):
        async def execute(self, _page: FakePage, decision: AgentDecision) -> ActionExecution:
            self.calls += 1
            return ActionExecution(True, self.render_code(decision))

    actions = SuccessfulAssertionActions()
    service.actions = actions

    result = asyncio.run(
        service._run_agent_loop(
            page=FakePage(),
            url="https://example.com",
            goal="验证标题",
            agent=RepeatingSuccessfulAssertionAgent(),
        )
    )

    assert result.status == "passed"
    assert actions.calls == 1
    assert len(result.steps) == 2
    assert result.steps[0].action.action == "assert_title"
    assert result.steps[0].success is True
    assert result.steps[-1].action.action == "finish"
    assert "自动完成" in result.steps[-1].action.message


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


def test_agent_does_not_execute_identical_failed_action_twice(tmp_path: Path) -> None:
    settings = SimpleNamespace(
        browsers_path=tmp_path,
        agent_action_timeout_ms=1000,
        agent_max_steps=5,
        agent_max_consecutive_failures=3,
    )
    service = PlaywrightService(settings)
    service.observer = FakeObserver()
    actions = FakeActions()
    service.actions = actions

    result = asyncio.run(
        service._run_agent_loop(
            page=FakePage(),
            url="https://example.com",
            goal="点击按钮",
            agent=RepeatingAgent(),
        )
    )

    assert result.status == "failed"
    assert actions.calls == 1
    assert len(result.steps) == 3
    assert "拒绝重复执行" in (result.steps[1].error or "")


def test_resolve_element_reference_uses_current_observation_locator() -> None:
    observation = PageObservation(
        url="https://example.com",
        title="Test App",
        aria_snapshot='- textbox "搜索"',
        element_refs={
            "el_001": LocatorTarget(
                strategy="css",
                value='[data-ai-test-ref="el_001"]',
            )
        },
    )
    decision = AgentDecision(action="fill", element_ref="el_001", value="人工智能")

    resolved = PlaywrightService._resolve_element_reference(decision, observation)

    assert resolved.target is not None
    assert resolved.target.strategy == "css"
    assert resolved.target.value == '[data-ai-test-ref="el_001"]'


def test_stale_element_reference_falls_back_to_legacy_target() -> None:
    observation = PageObservation(
        url="https://example.com",
        title="Test App",
        aria_snapshot="",
    )
    fallback = LocatorTarget(strategy="id", value="search")
    decision = AgentDecision(
        action="fill",
        element_ref="el_999",
        target=fallback,
        value="人工智能",
    )

    resolved = PlaywrightService._resolve_element_reference(decision, observation)

    assert resolved.element_ref is None
    assert resolved.target == fallback
