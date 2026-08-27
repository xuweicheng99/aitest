import asyncio

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentDecision, LocatorTarget
from app.services.browser_action_service import BrowserActionService


def test_role_click_renders_playwright_code() -> None:
    decision = AgentDecision(
        action="click",
        target=LocatorTarget(strategy="role", role="button", value="登录", exact=True),
    )
    assert BrowserActionService.render_code(decision) == (
        "await page.get_by_role('button', name='登录', exact=True).click()"
    )


def test_fill_requires_value() -> None:
    with pytest.raises(ValidationError):
        AgentDecision(
            action="fill",
            target=LocatorTarget(strategy="label", value="用户名"),
        )


def test_role_target_requires_role() -> None:
    with pytest.raises(ValidationError):
        LocatorTarget(strategy="role", value="提交")


def test_id_target_renders_css_id_locator() -> None:
    decision = AgentDecision(
        action="fill",
        target=LocatorTarget(strategy="id", value="kw"),
        value="人工智能",
    )
    assert BrowserActionService.render_code(decision) == (
        "await page.locator('#kw').fill('人工智能')"
    )


def test_finish_does_not_accept_target() -> None:
    decision = AgentDecision(action="finish", message="verified")
    assert decision.action == "finish"


def test_url_defaults_to_exact_but_can_use_contains() -> None:
    exact = AgentDecision(action="assert_url", expected="https://example.com")
    contains = AgentDecision(action="assert_url", expected="/results", match="contains")

    assert exact.match == "exact"
    assert contains.match == "contains"


class FakeLocator:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    async def click(self, **_kwargs) -> None:
        self.calls.append(self.name)
        if self.name == "missing":
            raise RuntimeError("元素不存在")


class FakeLocatorPage:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_by_text(self, value: str, **_kwargs) -> FakeLocator:
        return FakeLocator(value, self.calls)


def test_action_automatically_uses_fallback_locator() -> None:
    service = BrowserActionService(action_timeout_ms=1000)
    page = FakeLocatorPage()
    decision = AgentDecision(
        action="click",
        target=LocatorTarget(strategy="text", value="missing"),
        fallback_targets=[LocatorTarget(strategy="text", value="working")],
    )

    result = asyncio.run(service.execute(page, decision))

    assert result.success is True
    assert page.calls == ["missing", "working"]
    assert result.code == "await page.get_by_text('working').click()"


def test_url_and_title_assertions_support_match_modes() -> None:
    BrowserActionService._assert_value(
        "URL", "https://example.com/results?q=test", r"/results\?q=", "regex"
    )
    BrowserActionService._assert_value("标题", "Search results", "results", "contains")
    with pytest.raises(AssertionError):
        BrowserActionService._assert_value("标题", "Search results", "Search", "exact")


def test_navigation_error_explains_certificate_failure() -> None:
    message = BrowserActionService._navigation_error_message(
        RuntimeError("Page.goto: net::ERR_CERT_COMMON_NAME_INVALID")
    )
    assert "HTTPS 证书校验失败" in message
    assert "PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true" in message


class CandidateLocator:
    def __init__(
        self,
        *,
        visible: bool,
        calls: list[str],
        name: str,
        descriptor: dict | None = None,
    ) -> None:
        self.visible = visible
        self.calls = calls
        self.name = name
        self.descriptor = descriptor

    async def is_visible(self) -> bool:
        return self.visible

    async def is_editable(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def fill(self, value: str, **_kwargs) -> None:
        self.calls.append(f"{self.name}:{value}")

    async def click(self, **_kwargs) -> None:
        self.calls.append(f"click:{self.name}")

    async def evaluate(self, _script: str) -> dict:
        if self.descriptor is None:
            raise RuntimeError("descriptor unavailable")
        return self.descriptor


class MultiLocator:
    def __init__(self, candidates: list[CandidateLocator]) -> None:
        self.candidates = candidates

    async def count(self) -> int:
        return len(self.candidates)

    def nth(self, index: int) -> CandidateLocator:
        return self.candidates[index]


class MultiLocatorPage:
    def __init__(self, visible: list[bool]) -> None:
        self.calls: list[str] = []
        self.locator = MultiLocator(
            [
                CandidateLocator(visible=value, calls=self.calls, name=f"candidate-{index}")
                for index, value in enumerate(visible)
            ]
        )

    def get_by_placeholder(self, _value: str, **_kwargs) -> MultiLocator:
        return self.locator


def test_fill_selects_the_only_visible_candidate() -> None:
    service = BrowserActionService(action_timeout_ms=1000)
    page = MultiLocatorPage([False, True])
    decision = AgentDecision(
        action="fill",
        target=LocatorTarget(strategy="placeholder", value="搜索"),
        value="人工智能",
    )

    result = asyncio.run(service.execute(page, decision))

    assert result.success is True
    assert page.calls == ["candidate-1:人工智能"]
    assert ".nth(1).fill('人工智能')" in result.code


def test_fill_reports_structured_error_when_all_candidates_are_hidden() -> None:
    service = BrowserActionService(action_timeout_ms=1000)
    page = MultiLocatorPage([False, False])
    decision = AgentDecision(
        action="fill",
        target=LocatorTarget(strategy="placeholder", value="搜索"),
        value="人工智能",
    )

    result = asyncio.run(service.execute(page, decision))

    assert result.success is False
    assert result.failure_type == "not_visible"
    assert "[not_visible]" in (result.error or "")


def test_click_selects_first_viewport_candidate_when_duplicates_are_equivalent() -> None:
    calls: list[str] = []
    signature = {
        "tag": "input",
        "type": "submit",
        "name": "btnK",
        "value": "Google 搜索",
        "role": "",
        "ariaLabel": "Google 搜索",
        "text": "",
        "href": "",
        "formAction": "",
    }
    first = CandidateLocator(
        visible=True,
        calls=calls,
        name="first",
        descriptor={**signature, "inViewport": True, "top": 300, "left": 500},
    )
    second = CandidateLocator(
        visible=True,
        calls=calls,
        name="second",
        descriptor={**signature, "inViewport": True, "top": 500, "left": 500},
    )

    class Page:
        def locator(self, _value: str) -> MultiLocator:
            return MultiLocator([first, second])

    service = BrowserActionService(action_timeout_ms=1000)
    decision = AgentDecision(
        action="click",
        target=LocatorTarget(strategy="css", value="input[name='btnK']"),
    )
    result = asyncio.run(service.execute(Page(), decision))

    assert result.success is True
    assert calls == ["click:first"]
    assert ".nth(0).click()" in result.code
