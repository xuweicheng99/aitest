from __future__ import annotations

import base64

from playwright.async_api import Page

from app.core.config import Settings
from app.schemas.agent import LocatorTarget, PageObservation


INTERACTIVE_ELEMENTS_SCRIPT = """
(elements) => {
  window.__aiTestRefCounter = window.__aiTestRefCounter || 0;
  return elements
  .filter((element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const inViewport = rect.bottom > 0 && rect.right > 0 &&
      rect.top < window.innerHeight && rect.left < window.innerWidth;
    const topElement = document.elementFromPoint(
      Math.max(0, Math.min(window.innerWidth - 1, centerX)),
      Math.max(0, Math.min(window.innerHeight - 1, centerY))
    );
    const unobscured = !inViewport || !topElement ||
      element === topElement || element.contains(topElement) || topElement.contains(element);
    const visibleByBrowser = typeof element.checkVisibility === 'function'
      ? element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
    return visibleByBrowser &&
      style.pointerEvents !== 'none' && rect.width > 0 && rect.height > 0 && unobscured;
  })
  .slice(0, 100)
  .map((element) => {
    let ref = element.getAttribute('data-ai-test-ref');
    if (!ref) {
      window.__aiTestRefCounter += 1;
      ref = `el_${String(window.__aiTestRefCounter).padStart(3, '0')}`;
      element.setAttribute('data-ai-test-ref', ref);
    }
    return {
      ref,
      tag: element.tagName.toLowerCase(),
      id: element.id || null,
      name: element.getAttribute('name'),
      role: element.getAttribute('role'),
      text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 300),
      label: element.getAttribute('aria-label'),
      placeholder: element.getAttribute('placeholder'),
      test_id: element.getAttribute('data-testid'),
      type: element.getAttribute('type'),
      disabled: Boolean(element.disabled),
      editable: !element.disabled && !element.readOnly &&
        (element.matches('input,textarea,select') || element.isContentEditable),
      locator_strategy: 'css',
      locator_value: `[data-ai-test-ref="${ref}"]`
    };
  });
}
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
        element_refs = self._build_element_refs(interactive_elements)
        return PageObservation(
            url=page.url,
            title=title,
            dom_snapshot=dom_snapshot[: self.settings.agent_dom_chars],
            aria_snapshot=aria_snapshot[: self.settings.agent_observation_chars],
            interactive_elements=interactive_elements,
            element_refs=element_refs,
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

    @staticmethod
    def _build_element_refs(
        elements: list[dict[str, str | bool | None]],
    ) -> dict[str, LocatorTarget]:
        refs: dict[str, LocatorTarget] = {}
        for element in elements:
            ref = element.get("ref")
            strategy = element.get("locator_strategy")
            value = element.get("locator_value")
            if not isinstance(ref, str) or not isinstance(strategy, str) or not isinstance(value, str) or not value:
                continue
            role = element.get("role")
            if strategy == "label" and not value:
                continue
            if strategy == "role":
                strategy = "text"
            try:
                refs[ref] = LocatorTarget(
                    strategy=strategy,
                    value=value,
                    role=role if isinstance(role, str) and role else None,
                )
            except Exception:
                continue
        return refs

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
