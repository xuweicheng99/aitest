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
