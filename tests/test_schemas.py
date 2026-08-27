import pytest
from pydantic import ValidationError

from app.schemas.run import RunRequest
from app.schemas.test_plan import TestCase


def test_normalize_request() -> None:
    request = RunRequest(url="  https://example.com  ", goal="  check title  ")
    assert request.url == "https://example.com"
    assert request.goal == "check title"


def test_reject_non_http_url() -> None:
    with pytest.raises(ValidationError):
        RunRequest(url="file:///etc/passwd", goal="read file")


def test_reject_url_without_host() -> None:
    with pytest.raises(ValidationError):
        RunRequest(url="https://", goal="open page")


def test_reject_url_with_credentials() -> None:
    with pytest.raises(ValidationError):
        RunRequest(url="https://user:password@example.com", goal="open page")


def test_test_case_rejects_blank_steps_after_normalization() -> None:
    with pytest.raises(ValidationError):
        TestCase(
            case_id="TC-001",
            title="登录测试",
            steps=["  "],
            expected_results=["登录成功"],
        )
