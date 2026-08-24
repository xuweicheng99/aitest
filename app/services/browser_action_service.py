from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Locator, Page, expect

from app.schemas.agent import AgentDecision, LocatorTarget


@dataclass(slots=True)
class ActionExecution:
    success: bool
    code: str
    error: str | None = None


class BrowserActionService:
    def __init__(self, action_timeout_ms: int) -> None:
        self.action_timeout_ms = action_timeout_ms

    async def execute(self, page: Page, decision: AgentDecision) -> ActionExecution:
        code = self.render_code(decision)
        try:
            await self._execute(page, decision)
            return ActionExecution(success=True, code=code)
        except Exception as exc:
            return ActionExecution(
                success=False,
                code=code,
                error=str(exc) or exc.__class__.__name__,
            )

    async def _execute(self, page: Page, decision: AgentDecision) -> None:
        action = decision.action
        if action in {"finish", "fail"}:
            return
        if action == "navigate":
            value = decision.value or ""
            if urlparse(value).scheme not in {"http", "https"}:
                raise ValueError("Agent 只能导航到 HTTP 或 HTTPS 地址")
            await page.goto(value, wait_until="domcontentloaded", timeout=self.action_timeout_ms)
            return
        if action == "assert_url":
            if page.url.rstrip("/") != (decision.expected or "").rstrip("/"):
                raise AssertionError(
                    f"页面 URL 不符合预期：实际 {page.url}，预期 {decision.expected}"
                )
            return

        locator = self._locator(page, decision.target)
        if action == "click":
            await locator.click(timeout=self.action_timeout_ms)
        elif action == "fill":
            await locator.fill(decision.value or "", timeout=self.action_timeout_ms)
        elif action == "press":
            await locator.press(decision.key or "", timeout=self.action_timeout_ms)
        elif action == "check":
            await locator.check(timeout=self.action_timeout_ms)
        elif action == "uncheck":
            await locator.uncheck(timeout=self.action_timeout_ms)
        elif action == "select":
            await locator.select_option(decision.value or "", timeout=self.action_timeout_ms)
        elif action == "assert_visible":
            await expect(locator).to_be_visible(timeout=self.action_timeout_ms)
        elif action == "assert_text":
            await expect(locator).to_contain_text(
                decision.expected or "",
                timeout=self.action_timeout_ms,
            )
        else:
            raise ValueError(f"不支持的 Agent 动作：{action}")

    @staticmethod
    def _locator(page: Page, target: LocatorTarget | None) -> Locator:
        if target is None:
            raise ValueError("动作缺少定位器")
        if target.strategy == "role":
            return page.get_by_role(
                target.role or "",
                name=target.value,
                exact=target.exact,
            )
        if target.strategy == "label":
            return page.get_by_label(target.value, exact=target.exact)
        if target.strategy == "placeholder":
            return page.get_by_placeholder(target.value, exact=target.exact)
        if target.strategy == "text":
            return page.get_by_text(target.value, exact=target.exact)
        if target.strategy == "test_id":
            return page.get_by_test_id(target.value)
        return page.locator(target.value)

    @classmethod
    def render_code(cls, decision: AgentDecision) -> str:
        action = decision.action
        if action == "navigate":
            return f"await page.goto({decision.value!r}, wait_until='domcontentloaded')"
        if action == "assert_url":
            return f"assert page.url.rstrip('/') == {decision.expected!r}.rstrip('/')"
        if action == "finish":
            return f"# Agent finished: {decision.message}"
        if action == "fail":
            return f"# Agent failed: {decision.message}"

        locator = cls._render_locator(decision.target)
        if action == "click":
            return f"await {locator}.click()"
        if action == "fill":
            return f"await {locator}.fill({decision.value!r})"
        if action == "press":
            return f"await {locator}.press({decision.key!r})"
        if action in {"check", "uncheck"}:
            return f"await {locator}.{action}()"
        if action == "select":
            return f"await {locator}.select_option({decision.value!r})"
        if action == "assert_visible":
            return f"await expect({locator}).to_be_visible()"
        if action == "assert_text":
            return f"await expect({locator}).to_contain_text({decision.expected!r})"
        return f"# Unsupported action: {action}"

    @staticmethod
    def _render_locator(target: LocatorTarget | None) -> str:
        if target is None:
            return "page"
        exact = ", exact=True" if target.exact else ""
        if target.strategy == "role":
            return f"page.get_by_role({target.role!r}, name={target.value!r}{exact})"
        method = {
            "label": "get_by_label",
            "placeholder": "get_by_placeholder",
            "text": "get_by_text",
            "test_id": "get_by_test_id",
            "css": "locator",
        }[target.strategy]
        return f"page.{method}({target.value!r}{exact if target.strategy not in {'test_id', 'css'} else ''})"

