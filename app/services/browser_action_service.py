from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect

from app.schemas.agent import AgentDecision, LocatorTarget


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ActionExecution:
    success: bool
    code: str
    error: str | None = None
    failure_type: str | None = None
    failure_signature: str | None = None
    used_target: LocatorTarget | None = None


class BrowserActionService:
    def __init__(self, action_timeout_ms: int, navigation_timeout_ms: int | None = None) -> None:
        self.action_timeout_ms = action_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms or max(action_timeout_ms, 30_000)

    async def navigate(self, page: Page, url: str) -> None:
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("Agent 只能导航到 HTTP 或 HTTPS 地址")

        navigation_error: Exception | None = None
        try:
            await page.goto(
                url,
                wait_until="commit",
                timeout=self.navigation_timeout_ms,
            )
        except Exception as exc:
            navigation_error = exc
            if not await self._page_is_usable(page):
                message = self._navigation_error_message(exc)
                raise RuntimeError(f"页面导航失败，且未检测到可用内容：{message}") from exc

        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=min(self.navigation_timeout_ms, 10_000),
            )
        except PlaywrightTimeoutError as exc:
            if not await self._page_is_usable(page):
                raise RuntimeError(
                    "页面已建立连接，但等待 DOM 就绪超时，且未检测到可用页面内容"
                ) from exc
            logger.info(
                "Continuing after DOMContentLoaded timeout because the page is usable: %s",
                page.url,
            )

        if navigation_error is not None:
            logger.info(
                "Continuing after navigation error because the page is usable: %s (%s)",
                page.url,
                navigation_error,
            )

    async def _page_is_usable(self, page: Page) -> bool:
        current_url = page.url
        if urlparse(current_url).scheme not in {"http", "https"}:
            return False
        try:
            state = await page.locator("body").evaluate(
                """
                (body) => ({
                  childCount: body.children.length,
                  textLength: (body.innerText || '').trim().length,
                  htmlLength: body.innerHTML.length
                })
                """,
                timeout=min(self.action_timeout_ms, 3_000),
            )
            if isinstance(state, dict) and (
                int(state.get("childCount", 0)) > 0
                or int(state.get("textLength", 0)) > 0
                or int(state.get("htmlLength", 0)) > 32
            ):
                return True
        except Exception:
            pass
        try:
            title = (await page.title()).strip()
            return bool(title and not title.lower().startswith("loading "))
        except Exception:
            return False

    @staticmethod
    def _navigation_error_message(exc: Exception) -> str:
        message = str(exc) or exc.__class__.__name__
        lowered = message.lower()
        certificate_markers = (
            "err_cert_",
            "certificate",
            "ssl_error",
            "self signed",
            "hostname mismatch",
        )
        if any(marker in lowered for marker in certificate_markers):
            return (
                f"HTTPS 证书校验失败：{message}。请确认域名拼写和证书是否匹配；"
                "仅在可信测试环境中将 PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true"
            )
        if "name_not_resolved" in lowered or "dns" in lowered:
            return f"域名解析失败：{message}。请确认 URL 和网络连接"
        if "timeout" in lowered:
            return f"页面导航超时：{message}。请检查目标站点是否可访问"
        return message

    async def execute(self, page: Page, decision: AgentDecision) -> ActionExecution:
        try:
            used_target, target_index = await self._execute(page, decision)
            executed_decision = decision
            if used_target is not None and used_target != decision.target:
                executed_decision = decision.model_copy(
                    update={"target": used_target, "fallback_targets": []}
                )
            return ActionExecution(
                success=True,
                code=self.render_code(executed_decision, target_index=target_index),
                used_target=used_target,
            )
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            failure_type = self._failure_type(error)
            return ActionExecution(
                success=False,
                code=self.render_code(decision),
                error=error,
                failure_type=failure_type,
                failure_signature=f"{decision.action}:{failure_type}",
            )

    async def _execute(
        self, page: Page, decision: AgentDecision
    ) -> tuple[LocatorTarget | None, int | None]:
        action = decision.action
        if action in {"finish", "fail"}:
            return None, None
        if action == "navigate":
            value = decision.value or ""
            await self.navigate(page, value)
            return None, None
        if action == "assert_url":
            self._assert_value("页面 URL", page.url, decision.expected or "", decision.match, normalize_url=True)
            return None, None
        if action == "assert_title":
            self._assert_value("页面标题", await page.title(), decision.expected or "", decision.match)
            return None, None

        targets: list[LocatorTarget] = []
        for target in [decision.target, *decision.fallback_targets]:
            if target is not None and target not in targets:
                targets.append(target)
        errors: list[str] = []
        timeout = max(1, self.action_timeout_ms // len(targets))
        for target in targets:
            try:
                target_index = await self._execute_on_locator(page, decision, target, timeout)
                return target, target_index
            except Exception as exc:
                errors.append(
                    f"{self._describe_target(target)}: {str(exc) or exc.__class__.__name__}"
                )
        raise RuntimeError("所有定位策略均失败；" + " | ".join(errors))

    async def _execute_on_locator(
        self,
        page: Page,
        decision: AgentDecision,
        target: LocatorTarget | None,
        timeout: int,
    ) -> int | None:
        action = decision.action
        locator, target_index = await self._resolve_actionable_locator(
            self._locator(page, target), action
        )
        if action == "click":
            await locator.click(timeout=timeout)
        elif action == "fill":
            await locator.fill(decision.value or "", timeout=timeout)
        elif action == "press":
            await locator.press(decision.key or "", timeout=timeout)
        elif action == "check":
            await locator.check(timeout=timeout)
        elif action == "uncheck":
            await locator.uncheck(timeout=timeout)
        elif action == "select":
            await locator.select_option(decision.value or "", timeout=timeout)
        elif action == "assert_visible":
            await expect(locator).to_be_visible(timeout=timeout)
        elif action == "assert_text":
            expected: str | re.Pattern[str] = decision.expected or ""
            if decision.match == "regex":
                expected = re.compile(expected)
            if decision.match == "exact":
                await expect(locator).to_have_text(expected, timeout=timeout)
            else:
                await expect(locator).to_contain_text(expected, timeout=timeout)
        else:
            raise ValueError(f"不支持的 Agent 动作：{action}")
        return target_index

    @staticmethod
    async def _resolve_actionable_locator(
        locator: Locator, action: str
    ) -> tuple[Locator, int | None]:
        # Keep lightweight locator test doubles and compatible Playwright wrappers usable.
        if not hasattr(locator, "count"):
            return locator, None
        count = await locator.count()
        if count == 0:
            raise RuntimeError("[no_match] 定位器没有匹配任何元素")

        visible: list[tuple[int, Locator]] = []
        for index in range(min(count, 50)):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    visible.append((index, candidate))
            except Exception:
                continue

        if not visible:
            raise RuntimeError(f"[not_visible] 匹配到 {count} 个元素，但没有可见元素")

        actionable: list[tuple[int, Locator]] = []
        for index, candidate in visible:
            try:
                if action in {"fill", "press"} and not await candidate.is_editable():
                    continue
                if action in {"click", "check", "uncheck", "select"} and not await candidate.is_enabled():
                    continue
                actionable.append((index, candidate))
            except Exception:
                continue

        if not actionable:
            raise RuntimeError(
                f"[not_actionable] 匹配到 {len(visible)} 个可见元素，但均不可操作"
            )
        if len(actionable) > 1:
            equivalent = await BrowserActionService._equivalent_candidates(actionable)
            if equivalent is not None:
                return equivalent
            raise RuntimeError(
                f"[ambiguous] 定位器匹配到 {len(actionable)} 个语义不同的可见可操作元素，"
                "请提供更精确的 role、label、test_id 或 CSS 父容器"
            )

        index, candidate = actionable[0]
        return candidate, index if count > 1 else None

    @staticmethod
    async def _equivalent_candidates(
        candidates: list[tuple[int, Locator]],
    ) -> tuple[Locator, int] | None:
        descriptors: list[tuple[int, Locator, dict[str, object]]] = []
        script = """
        (element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName.toLowerCase(),
            type: element.getAttribute('type') || '',
            name: element.getAttribute('name') || '',
            value: element.getAttribute('value') || '',
            role: element.getAttribute('role') || '',
            ariaLabel: element.getAttribute('aria-label') || '',
            text: (element.innerText || '').trim(),
            href: element.getAttribute('href') || '',
            formAction: element.getAttribute('formaction') || '',
            inViewport: rect.bottom > 0 && rect.right > 0 &&
              rect.top < window.innerHeight && rect.left < window.innerWidth,
            top: rect.top,
            left: rect.left
          };
        }
        """
        for index, candidate in candidates:
            if not hasattr(candidate, "evaluate"):
                return None
            try:
                descriptor = await candidate.evaluate(script)
            except Exception:
                return None
            if not isinstance(descriptor, dict):
                return None
            descriptors.append((index, candidate, descriptor))

        semantic_keys = (
            "tag",
            "type",
            "name",
            "value",
            "role",
            "ariaLabel",
            "text",
            "href",
            "formAction",
        )
        signatures = {
            tuple(str(descriptor.get(key, "")) for key in semantic_keys)
            for _, _, descriptor in descriptors
        }
        if len(signatures) != 1:
            return None

        index, candidate, _descriptor = min(
            descriptors,
            key=lambda item: (
                0 if item[2].get("inViewport") else 1,
                float(item[2].get("top", 0)),
                float(item[2].get("left", 0)),
                item[0],
            ),
        )
        return candidate, index

    @staticmethod
    def _failure_type(error: str) -> str:
        for failure_type in (
            "no_match",
            "not_visible",
            "not_actionable",
            "ambiguous",
        ):
            if f"[{failure_type}]" in error:
                return failure_type
        lowered = error.lower()
        if "strict mode violation" in lowered:
            return "ambiguous"
        if "not visible" in lowered:
            return "not_visible"
        if "timeout" in lowered:
            return "timeout"
        return "execution_error"

    @staticmethod
    def _assert_value(
        label: str,
        actual: str,
        expected: str,
        match: str,
        *,
        normalize_url: bool = False,
    ) -> None:
        compared_actual = actual.rstrip("/") if normalize_url and match == "exact" else actual
        compared_expected = expected.rstrip("/") if normalize_url and match == "exact" else expected
        if match == "exact":
            matched = compared_actual == compared_expected
        elif match == "regex":
            matched = re.search(expected, actual) is not None
        else:
            matched = expected in actual
        if not matched:
            raise AssertionError(
                f"{label}不符合预期：实际 {actual!r}，{match} 预期 {expected!r}"
            )

    @staticmethod
    def _describe_target(target: LocatorTarget | None) -> str:
        if target is None:
            return "missing target"
        role = f"/{target.role}" if target.role else ""
        return f"{target.strategy}{role}={target.value!r}"

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
        if target.strategy == "id":
            return page.locator(f"#{target.value}")
        if target.strategy == "xpath":
            return page.locator(f"xpath={target.value}")
        return page.locator(target.value)

    @classmethod
    def render_code(cls, decision: AgentDecision, target_index: int | None = None) -> str:
        action = decision.action
        if action == "navigate":
            return f"await page.goto({decision.value!r}, wait_until='commit')"
        if action == "assert_url":
            return cls._render_value_assertion("page.url", decision)
        if action == "assert_title":
            return cls._render_value_assertion("await page.title()", decision)
        if action == "finish":
            return f"# Agent finished: {decision.message}"
        if action == "fail":
            return f"# Agent failed: {decision.message}"

        locator = cls._render_locator(decision.target, target_index)
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
            if decision.match == "exact":
                return f"await expect({locator}).to_have_text({decision.expected!r})"
            if decision.match == "regex":
                return f"await expect({locator}).to_contain_text(re.compile({decision.expected!r}))"
            return f"await expect({locator}).to_contain_text({decision.expected!r})"
        return f"# Unsupported action: {action}"

    @staticmethod
    def _render_value_assertion(actual: str, decision: AgentDecision) -> str:
        if decision.match == "exact":
            if decision.action == "assert_url":
                return f"assert {actual}.rstrip('/') == {decision.expected!r}.rstrip('/')"
            return f"assert {actual} == {decision.expected!r}"
        if decision.match == "regex":
            return f"assert re.search({decision.expected!r}, {actual})"
        return f"assert {decision.expected!r} in {actual}"

    @staticmethod
    def _render_locator(target: LocatorTarget | None, target_index: int | None = None) -> str:
        if target is None:
            return "page"
        exact = ", exact=True" if target.exact else ""
        if target.strategy == "role":
            rendered = f"page.get_by_role({target.role!r}, name={target.value!r}{exact})"
            return f"{rendered}.nth({target_index})" if target_index is not None else rendered
        method = {
            "label": "get_by_label",
            "placeholder": "get_by_placeholder",
            "text": "get_by_text",
            "test_id": "get_by_test_id",
            "id": "locator",
            "xpath": "locator",
            "css": "locator",
        }[target.strategy]
        value = (
            f"#{target.value}" if target.strategy == "id"
            else f"xpath={target.value}" if target.strategy == "xpath"
            else target.value
        )
        rendered = f"page.{method}({value!r}{exact if target.strategy not in {'test_id', 'id', 'css'} else ''})"
        return f"{rendered}.nth({target_index})" if target_index is not None else rendered
