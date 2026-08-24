import pytest
from pydantic import ValidationError

from app.schemas.run import RunRequest


def test_normalize_request() -> None:
    request = RunRequest(url="  https://example.com  ", goal="  check title  ")
    assert request.url == "https://example.com"
    assert request.goal == "check title"


def test_reject_non_http_url() -> None:
    with pytest.raises(ValidationError):
        RunRequest(url="file:///etc/passwd", goal="read file")

