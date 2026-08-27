from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.core.config import Settings
from app.schemas.agent import AgentDecision, AgentStep, LocatorTarget
from app.schemas.run import ArtifactLinks, ExecutionResult
from app.services.agent_service import AgentService
from app.services.browser_action_service import BrowserActionService
from app.services.page_observer import PageObserver


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentLoopResult:
    status: str
    error: str | None
    steps: list[AgentStep]
    code_lines: list[str]


class PlaywrightService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(settings.browsers_path))
        self.observer = PageObserver(settings)
        self.actions = BrowserActionService(
            settings.agent_action_timeout_ms,
            getattr(settings, "agent_navigation_timeout_ms", 30_000),
        )

    async def execute(
        self,
        *,
        url: str,
        goal: str,
        agent: AgentService,
        run_dir: Path,
        headless: bool | None,
    ) -> tuple[ExecutionResult, str]:
        started = time.perf_counter()
        effective_headless = self.settings.headless if headless is None else headless
        console_messages: list[str] = []
        page_errors: list[str] = []
        artifact_errors: list[str] = []
        status = "failed"
        error_message: str | None = None
        final_url = url
        final_title = ""
        agent_steps: list[AgentStep] = []
        code_lines = [
            "import re",
            "",
            "from playwright.async_api import expect",
            "",
            f"await page.goto({url!r}, wait_until='commit')",
        ]
        screenshot_path = run_dir / "screenshot.png"
        trace_path = run_dir / "trace.zip"
        browser: Browser | None = None
        context: BrowserContext | None = None
        page: Page | None = None
        tracing_started = False

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome",headless=effective_headless)
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    ignore_https_errors=getattr(self.settings, "ignore_https_errors", False),
                )
                await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                tracing_started = True
                page = await context.new_page()
                page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                try:
                    loop_result = await asyncio.wait_for(
                        self._run_agent_loop(page=page, url=url, goal=goal, agent=agent),
                        timeout=self.settings.test_timeout_seconds,
                    )
                    status = loop_result.status
                    error_message = loop_result.error
                    agent_steps = loop_result.steps
                    code_lines.extend(loop_result.code_lines)
                except TimeoutError:
                    error_message = f"Agent 测试超过 {self.settings.test_timeout_seconds} 秒"
                except Exception as exc:
                    error_message = str(exc) or exc.__class__.__name__
                    logger.exception("Agent loop failed")
                finally:
                    final_url = page.url
                    final_title = await self._safe_title(page)
                    await self._capture_artifacts(
                        page,
                        context,
                        screenshot_path,
                        trace_path,
                        tracing_started,
                        artifact_errors,
                    )
                    tracing_started = False
                await browser.close()
                browser = None
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            logger.exception("Playwright execution could not start")
        finally:
            if tracing_started and context is not None:
                try:
                    await context.tracing.stop(path=trace_path)
                except Exception as exc:
                    artifact_errors.append(f"Trace 保存失败：{exc}")
            if browser is not None:
                try:
                    await browser.close()
                except Exception as exc:
                    artifact_errors.append(f"浏览器关闭失败：{exc}")

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = ExecutionResult(
            status=status,
            error=error_message,
            url=url,
            final_url=final_url,
            title=final_title,
            duration_ms=duration_ms,
            console=console_messages[-self.settings.console_log_limit :],
            page_errors=page_errors[-self.settings.console_log_limit :],
            artifact_errors=artifact_errors,
            agent_steps=agent_steps,
            step_count=len(agent_steps),
            artifacts=ArtifactLinks(
                screenshot=f"/api/runs/{run_dir.name}/screenshot.png" if screenshot_path.is_file() else None,
                trace=f"/api/runs/{run_dir.name}/trace.zip" if trace_path.is_file() else None,
            ),
        )
        return result, "\n".join(code_lines)

    async def _run_agent_loop(
        self,
        *,
        page: Page,
        url: str,
        goal: str,
        agent: AgentService,
    ) -> AgentLoopResult:
        await self.actions.navigate(page, url)
        history: list[AgentStep] = []
        code_lines: list[str] = []
        last_error: str | None = None
        consecutive_failures = 0
        successful_assertion = False
        failed_action_fingerprints: set[str] = set()
        failed_target_fingerprints: set[str] = set()
        successful_assertion_fingerprints: set[str] = set()
        last_successful_input_target: LocatorTarget | None = None
        last_successful_input_url: str | None = None

        for step_number in range(1, self.settings.agent_max_steps + 1):
            observation = await self.observer.observe(page)
            observation_fingerprint = self._observation_fingerprint(observation)
            decision = await agent.decide(
                original_url=url,
                goal=goal,
                observation=observation,
                history=history,
                step_number=step_number,
                remaining_steps=self.settings.agent_max_steps - step_number,
                last_error=last_error,
            )
            try:
                decision = self._resolve_element_reference(decision, observation)
            except ValueError as exc:
                error = str(exc)
                history.append(
                    AgentStep(
                        step=step_number,
                        url=observation.url,
                        title=observation.title,
                        action=decision,
                        success=False,
                        error=error,
                    )
                )
                last_error = error
                consecutive_failures += 1
                if consecutive_failures >= self.settings.agent_max_consecutive_failures:
                    return AgentLoopResult("failed", error, history, code_lines)
                continue

            if (
                decision.action in {"fill", "press"}
                and last_successful_input_target is not None
                and last_successful_input_url == observation.url
            ):
                if any(
                    f"{observation_fingerprint}:{self._target_fingerprint(target)}"
                    in failed_target_fingerprints
                    for target in self._decision_targets(decision)
                ):
                    decision = decision.model_copy(
                        update={
                            "target": last_successful_input_target,
                            "fallback_targets": [],
                        }
                    )

            if decision.action == "finish":
                if not successful_assertion or last_error is not None:
                    error = (
                        "完成测试前必须至少执行一个成功断言，且最后一个动作不能处于失败状态"
                    )
                    history.append(
                        AgentStep(
                            step=step_number,
                            url=observation.url,
                            title=observation.title,
                            action=decision,
                            success=False,
                            error=error,
                        )
                    )
                    last_error = error
                    consecutive_failures += 1
                    if consecutive_failures >= self.settings.agent_max_consecutive_failures:
                        return AgentLoopResult("failed", error, history, code_lines)
                    continue
                history.append(
                    AgentStep(
                        step=step_number,
                        url=observation.url,
                        title=observation.title,
                        action=decision,
                        success=True,
                    )
                )
                code_lines.append(self.actions.render_code(decision))
                return AgentLoopResult("passed", None, history, code_lines)

            if decision.action == "fail":
                message = decision.message or "AI Agent 判断测试目标无法完成"
                history.append(
                    AgentStep(
                        step=step_number,
                        url=observation.url,
                        title=observation.title,
                        action=decision,
                        success=False,
                        error=message,
                    )
                )
                code_lines.append(self.actions.render_code(decision))
                return AgentLoopResult("failed", message, history, code_lines)

            fingerprint = self._action_fingerprint(decision)
            if decision.action.startswith("assert_") and fingerprint in successful_assertion_fingerprints:
                message = "重复成功断言，自动完成测试"
                finish = AgentDecision(action="finish", message=message)
                history.append(
                    AgentStep(
                        step=step_number,
                        url=observation.url,
                        title=observation.title,
                        action=finish,
                        success=True,
                    )
                )
                code_lines.append(self.actions.render_code(finish))
                return AgentLoopResult("passed", None, history, code_lines)

            if fingerprint in failed_action_fingerprints:
                error = (
                    "拒绝重复执行已失败的完全相同动作；"
                    "请根据当前 DOM、ARIA 和截图更换定位策略或操作"
                )
                history.append(
                    AgentStep(
                        step=step_number,
                        url=observation.url,
                        title=observation.title,
                        action=decision,
                        success=False,
                        error=error,
                    )
                )
                last_error = error
                consecutive_failures += 1
                if consecutive_failures >= self.settings.agent_max_consecutive_failures:
                    return AgentLoopResult(
                        "failed",
                        f"连续 {consecutive_failures} 个 Agent 动作执行失败：{last_error}",
                        history,
                        code_lines,
                    )
                continue

            execution = await self.actions.execute(page, decision)
            code_lines.append(execution.code)
            history.append(
                AgentStep(
                    step=step_number,
                    url=observation.url,
                    title=observation.title,
                    action=decision,
                    success=execution.success,
                    error=execution.error,
                )
            )
            last_error = execution.error
            if execution.success:
                consecutive_failures = 0
                if decision.action in {"fill", "press"} and execution.used_target is not None:
                    last_successful_input_target = execution.used_target
                    last_successful_input_url = observation.url
                if decision.action.startswith("assert_"):
                    successful_assertion = True
                    successful_assertion_fingerprints.add(fingerprint)
            else:
                failed_action_fingerprints.add(fingerprint)
                failed_target_fingerprints.update(
                    f"{observation_fingerprint}:{self._target_fingerprint(target)}"
                    for target in self._decision_targets(decision)
                )
                consecutive_failures += 1
                if consecutive_failures >= self.settings.agent_max_consecutive_failures:
                    return AgentLoopResult(
                        "failed",
                        f"连续 {consecutive_failures} 个 Agent 动作执行失败：{last_error}",
                        history,
                        code_lines,
                    )

        return AgentLoopResult(
            "failed",
            f"达到最大 Agent 步数 {self.settings.agent_max_steps}，测试目标仍未完成",
            history,
            code_lines,
        )

    @staticmethod
    def _action_fingerprint(decision: AgentDecision) -> str:
        payload = decision.model_dump(exclude={"message"})
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _resolve_element_reference(
        decision: AgentDecision,
        observation,
    ) -> AgentDecision:
        if not decision.element_ref:
            return decision
        target = observation.element_refs.get(decision.element_ref)
        if target is None:
            if decision.target is not None:
                return decision.model_copy(update={"element_ref": None})
            available = ", ".join(list(observation.element_refs)[:20]) or "无"
            raise ValueError(
                f"[stale_element_ref] 当前页面不存在元素引用 {decision.element_ref!r}；"
                f"可用引用：{available}"
            )
        return decision.model_copy(
            update={
                "target": target,
                "fallback_targets": [],
            }
        )

    @staticmethod
    def _decision_targets(decision: AgentDecision) -> list[LocatorTarget]:
        return [
            target
            for target in [decision.target, *decision.fallback_targets]
            if target is not None
        ]

    @staticmethod
    def _target_fingerprint(target: LocatorTarget) -> str:
        return json.dumps(
            target.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _observation_fingerprint(observation) -> str:
        payload = {
            "url": observation.url,
            "title": observation.title,
            "aria": observation.aria_snapshot,
            "interactive": observation.interactive_elements,
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    async def _safe_title(page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""

    @staticmethod
    async def _capture_artifacts(
        page: Page,
        context: BrowserContext,
        screenshot_path: Path,
        trace_path: Path,
        tracing_started: bool,
        errors: list[str],
    ) -> None:
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
        except Exception as exc:
            errors.append(f"截图保存失败：{exc}")
        if tracing_started:
            try:
                await context.tracing.stop(path=trace_path)
            except Exception as exc:
                errors.append(f"Trace 保存失败：{exc}")
