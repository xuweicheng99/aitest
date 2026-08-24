from __future__ import annotations

import base64

from playwright.async_api import Page

from app.core.config import Settings
from app.schemas.agent import PageObservation


INTERACTIVE_ELEMENTS_SCRIPT = """
(elements) => elements
  .filter((element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  })
  .slice(0, 100)
  .map((element) => ({
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute('role'),
    text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 300),
    label: element.getAttribute('aria-label'),
    placeholder: element.getAttribute('placeholder'),
    test_id: element.getAttribute('data-testid'),
    type: element.getAttribute('type'),
    disabled: Boolean(element.disabled)
  }))
"""


class PageObserver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def observe(self, page: Page) -> PageObservation:
        await page.wait_for_timeout(self.settings.agent_observation_delay_ms)
        title = await self._safe_title(page)
        dom_snapshot = await self._dom_snapshot(page)
        aria_snapshot = await self._aria_snapshot(page)
        interactive_elements = await self._interactive_elements(page)
        screenshot_data_url = await self._screenshot_data_url(page)
        return PageObservation(
            url=page.url,
            title=title,
            dom_snapshot=dom_snapshot[: self.settings.agent_dom_chars],
            aria_snapshot=aria_snapshot[: self.settings.agent_observation_chars],
            interactive_elements=interactive_elements,
            screenshot_data_url=screenshot_data_url,
        )

    @staticmethod
    async def _dom_snapshot(page: Page) -> str:
        script = """
        (body) => {
          const clone = body.cloneNode(true);
          clone.querySelectorAll('script,style,noscript,template').forEach((node) => node.remove());
          clone.querySelectorAll('*').forEach((node) => {
            for (const attribute of [...node.attributes]) {
              if (attribute.name.startsWith('on') || attribute.name === 'style') {
                node.removeAttribute(attribute.name);
              }
            }
          });
          return clone.outerHTML;
        }
        """
        try:
            value = await page.locator("body").evaluate(script, timeout=5000)
            return value if isinstance(value, str) else ""
        except Exception:
            return ""

    async def _aria_snapshot(self, page: Page) -> str:
        try:
            return await page.locator("body").aria_snapshot(timeout=5000)
        except Exception:
            try:
                return await page.locator("body").inner_text(timeout=5000)
            except Exception:
                return "页面内容暂时无法读取"

    @staticmethod
    async def _interactive_elements(page: Page) -> list[dict[str, str | bool | None]]:
        selector = "a,button,input,textarea,select,[role='button'],[role='link'],[contenteditable='true']"
        try:
            values = await page.locator(selector).evaluate_all(INTERACTIVE_ELEMENTS_SCRIPT)
            return values if isinstance(values, list) else []
        except Exception:
            return []

    async def _screenshot_data_url(self, page: Page) -> str | None:
        if not self.settings.agent_include_screenshot:
            return None
        try:
            content = await page.screenshot(type="jpeg", quality=55, full_page=False)
            encoded = base64.b64encode(content).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            return None

    @staticmethod
    async def _safe_title(page: Page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""
