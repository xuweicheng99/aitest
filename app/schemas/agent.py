from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ActionType = Literal[
    "navigate",
    "click",
    "fill",
    "press",
    "check",
    "uncheck",
    "select",
    "assert_visible",
    "assert_text",
    "assert_url",
    "finish",
    "fail",
]


class LocatorTarget(BaseModel):
    strategy: Literal["role", "label", "placeholder", "text", "test_id", "css"]
    value: str = Field(..., min_length=1, max_length=1000)
    role: str | None = Field(default=None, max_length=100)
    exact: bool = False

    @model_validator(mode="after")
    def validate_role(self) -> "LocatorTarget":
        if self.strategy == "role" and not self.role:
            raise ValueError("role 定位器必须提供 role 字段")
        return self


class AgentDecision(BaseModel):
    action: ActionType
    target: LocatorTarget | None = None
    value: str | None = Field(default=None, max_length=4000)
    expected: str | None = Field(default=None, max_length=4000)
    key: str | None = Field(default=None, max_length=100)
    message: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "AgentDecision":
        target_actions = {
            "click",
            "fill",
            "press",
            "check",
            "uncheck",
            "select",
            "assert_visible",
            "assert_text",
        }
        if self.action in target_actions and self.target is None:
            raise ValueError(f"{self.action} 动作必须提供 target")
        if self.action in {"navigate", "fill", "select"} and self.value is None:
            raise ValueError(f"{self.action} 动作必须提供 value")
        if self.action == "press" and self.key is None:
            raise ValueError("press 动作必须提供 key")
        if self.action in {"assert_text", "assert_url"} and self.expected is None:
            raise ValueError(f"{self.action} 动作必须提供 expected")
        return self


class PageObservation(BaseModel):
    url: str
    title: str
    dom_snapshot: str = ""
    aria_snapshot: str
    interactive_elements: list[dict[str, str | bool | None]] = Field(default_factory=list)
    screenshot_data_url: str | None = Field(default=None, exclude=True)


class AgentStep(BaseModel):
    step: int
    url: str
    title: str
    action: AgentDecision
    success: bool
    error: str | None = None
