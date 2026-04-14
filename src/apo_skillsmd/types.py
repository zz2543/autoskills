"""Shared enums and small data models used across modules."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProviderName(str, Enum):
    """Supported LLM providers."""

    MINIMAX = "minimax"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    QWEN = "qwen"
    MOCK = "mock"


class SandboxProfileName(str, Enum):
    """Available sandbox profiles."""

    OFFLINE_LOCAL = "offline-local"
    OFFLINE_EXTENDED = "offline-extended"
    NETWORK_WHITELIST = "network-whitelist"


class MessageRole(str, Enum):
    """Normalized chat message roles used by the agent loop."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SafetySeverity(str, Enum):
    """Severity levels for safety findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SafetyAction(str, Enum):
    """Policy decisions emitted by the safety layer."""

    ALLOW = "allow"
    SOFT_REJECT = "soft_reject"
    HARD_REJECT = "hard_reject"


class TaskTestCase(BaseModel):
    """A deterministic verification case for one benchmark task."""

    case_id: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    expected_output: dict[str, Any] = Field(default_factory=dict)


class VerifierSpec(BaseModel):
    """Definition of how to verify a task result."""

    kind: str = "json"
    command: str | None = None
    expected_file: str | None = None
    expected_stdout_contains: str | None = None


class TaskSpec(BaseModel):
    """Normalized task description consumed by the agent and evaluator."""

    task_id: str
    domain: str = "general"
    description: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    verifier: VerifierSpec = Field(default_factory=VerifierSpec)
    test_cases: list[TaskTestCase] = Field(default_factory=list)


class SkillEvaluation(BaseModel):
    """Evaluation summary used by selection and experiments."""

    pass_rate: float = 0.0
    execution_tokens: int = 0
    success: bool = False
    notes: list[str] = Field(default_factory=list)
