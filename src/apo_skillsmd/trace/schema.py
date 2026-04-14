"""Structured trace schema aligned with the design document."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModuleEvent(BaseModel):
    """One execution event attributed to a module, tool, or function slot."""

    module: str
    entered: bool = True
    exceptions: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    output_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalOutput(BaseModel):
    """High-level outputs from the completed run."""

    files_created: list[str] = Field(default_factory=list)
    stdout: str = ""
    assistant_message: str = ""


class Trace(BaseModel):
    """Normalized execution trace used by mutation and selection."""

    skill_id: str
    task_id: str
    success: bool
    execution_tokens: int = 0
    module_events: list[ModuleEvent] = Field(default_factory=list)
    final_output: FinalOutput = Field(default_factory=FinalOutput)
