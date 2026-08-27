import asyncio
from types import SimpleNamespace

import pytest

from app.schemas.agent import PageObservation
from app.services.agent_service import AgentService


def test_parse_plain_json() -> None:
    parsed = AgentService._parse_json('{"action":"finish","message":"done"}')
    assert parsed["action"] == "finish"


def test_parse_markdown_json() -> None:
    parsed = AgentService._parse_json('```json\n{"action":"assert_url","expected":"https://example.com"}\n```')
    assert parsed["action"] == "assert_url"


def test_reject_non_object_json() -> None:
    with pytest.raises(ValueError):
        AgentService._parse_json('["not", "an", "object"]')


def test_normalize_common_locator_aliases() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "fill",
            "target": {"strategy": "css_selector", "selector": "#kw"},
            "value": "人工智能",
        }
    )
    assert normalized["target"] == {"strategy": "css", "selector": "#kw", "value": "#kw"}


def test_normalize_xpath_locator() -> None:
    normalized = AgentService._normalize_decision_payload(
        {"action": "click", "target": {"type": "xpath", "value": "//button"}}
    )
    assert normalized["target"]["strategy"] == "xpath"


def test_normalize_unknown_fallback_strategy_by_selector_shape() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "fill",
            "target": {"strategy": "id", "value": "kw"},
            "fallback_targets": [
                {"strategy": "custom_css_locator", "value": "input[name='wd']"},
                {"strategy": "element_text", "value": "百度一下"},
            ],
            "value": "人工智能",
        }
    )
    assert normalized["fallback_targets"][0]["strategy"] == "css"
    assert normalized["fallback_targets"][1]["strategy"] == "text"


def test_drop_unusable_fallback_target_without_value() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "click",
            "target": {"strategy": "text", "value": "搜索"},
            "fallback_targets": [{"strategy": "unknown"}],
        }
    )
    assert normalized["fallback_targets"] == []


def test_normalize_string_targets_and_fallback_alias_field() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "fill",
            "target": "#kw",
            "fallbacks": ["//input[@name='wd']"],
            "value": "人工智能",
        }
    )
    assert normalized["target"]["strategy"] == "css"
    assert normalized["fallback_targets"][0]["strategy"] == "xpath"


def test_normalize_by_and_selector_value_fields() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "click",
            "target": {"by": "get_by_role", "role": "button", "selector_value": "搜索"},
        }
    )
    assert normalized["target"]["strategy"] == "role"
    assert normalized["target"]["value"] == "搜索"


def test_normalize_navigation_url_from_target_value() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "go_to",
            "target": {"strategy": "css", "value": "https://www.baidu.com"},
        }
    )
    assert normalized["action"] == "navigate"
    assert normalized["value"] == "https://www.baidu.com"
    assert normalized["target"] is None


def test_normalize_markdown_navigation_url() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "navigate",
            "target": {
                "strategy": "css",
                "value": "[https://www.baidu.com](https://www.baidu.com)",
            },
        }
    )
    assert normalized["value"] == "https://www.baidu.com"
    assert normalized["target"] is None


def test_normalize_element_ref_and_action_specific_aliases() -> None:
    normalized = AgentService._normalize_decision_payload(
        {
            "action": "fill",
            "ref": "el_003",
            "text": "人工智能",
            "match": "include",
        }
    )
    assert normalized["element_ref"] == "el_003"
    assert normalized["value"] == "人工智能"
    assert normalized["match"] == "contains"


def test_normalize_match_aliases() -> None:
    assert AgentService._normalize_match_value("equals") == "exact"
    assert AgentService._normalize_match_value("regexp") == "regex"
    assert AgentService._normalize_match_value("unknown") == "contains"


def test_normalize_assert_url_defaults_to_exact() -> None:
    normalized = AgentService._normalize_decision_payload(
        {"action": "assert_url", "expected": "https://example.com"}
    )
    assert normalized["match"] == "exact"


def test_llm_decision_sends_page_state_and_screenshot(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"assert_visible","target":{"strategy":"role","role":"button","value":"提交"},"message":"验证按钮"}'
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr("app.services.agent_service.httpx.AsyncClient", FakeClient)
    settings = SimpleNamespace(
        mock_mode=False,
        api_key="test-key",
        model="vision-model",
        json_response_mode=True,
        base_url="https://model.example/v1",
        model_timeout_seconds=30,
        agent_history_limit=8,
    )
    service = AgentService(settings)
    observation = PageObservation(
        url="https://app.example",
        title="Example",
        dom_snapshot='<button aria-label="提交">提交</button>',
        aria_snapshot='- button "提交"',
        interactive_elements=[{"tag": "button", "text": "提交"}],
        screenshot_data_url="data:image/jpeg;base64,AAAA",
    )

    decision = asyncio.run(
        service.decide(
            original_url="https://app.example",
            goal="验证提交按钮可见",
            observation=observation,
            history=[],
            step_number=1,
            remaining_steps=11,
            last_error=None,
        )
    )

    assert decision.action == "assert_visible"
    assert captured["url"] == "https://model.example/v1/chat/completions"
    user_content = captured["payload"]["messages"][1]["content"]
    assert user_content[0]["type"] == "text"
    assert '"dom_snapshot": "<button' in user_content[0]["text"]
    assert '"aria_snapshot": "- button \\"提交\\""' in user_content[0]["text"]
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_llm_retries_once_when_action_schema_is_invalid(monkeypatch) -> None:
    responses = iter(
        [
            '{"action":"click","target":{"strategy":"unknown_widget","value":"搜索"}}',
            '{"action":"click","target":{"strategy":"text","value":"搜索"}}',
        ]
    )
    calls: list[dict] = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": next(responses)}}]}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, _url: str, **kwargs):
            calls.append(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr("app.services.agent_service.httpx.AsyncClient", FakeClient)
    settings = SimpleNamespace(
        mock_mode=False,
        api_key="test-key",
        model="test-model",
        json_response_mode=True,
        base_url="https://model.example/v1",
        model_timeout_seconds=30,
        agent_history_limit=8,
    )
    service = AgentService(settings)
    observation = PageObservation(
        url="https://app.example",
        title="Example",
        aria_snapshot='- button "搜索"',
    )

    decision = asyncio.run(
        service.decide(
            original_url="https://app.example",
            goal="点击搜索",
            observation=observation,
            history=[],
            step_number=1,
            remaining_steps=11,
            last_error=None,
        )
    )

    assert decision.target is not None
    assert decision.target.strategy == "text"
    assert len(calls) == 2
