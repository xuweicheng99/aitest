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


def test_finish_does_not_accept_target() -> None:
    decision = AgentDecision(action="finish", message="verified")
    assert decision.action == "finish"
