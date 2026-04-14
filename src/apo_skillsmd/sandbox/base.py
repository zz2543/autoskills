"""Sandbox abstractions for safe skill execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import SandboxProfileName


class CommandResult(BaseModel):
    """Result of one shell command executed inside the sandbox."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    changed_files: list[str] = Field(default_factory=list)


class Sandbox(ABC):
    """Backend interface used by the agent tool layer."""

    profile: SandboxProfileName

    def __init__(self, profile: SandboxProfileName) -> None:
        self.profile = profile

    @abstractmethod
    def setup(self, *, skill: Skill | None = None) -> None:
        """Prepare the workspace and optionally materialize the skill files."""

    @abstractmethod
    def teardown(self) -> None:
        """Release sandbox resources."""

    @abstractmethod
    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        """Execute a shell command within the sandbox workspace."""

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read one file from the workspace."""

    @abstractmethod
    def write_file(self, path: str, content: str) -> str:
        """Write one file into the workspace."""

    @abstractmethod
    def list_files(self, path: str = ".") -> list[str]:
        """List files or directories relative to the sandbox root."""

    @abstractmethod
    def workspace_root(self) -> Path:
        """Return the root path of the current sandbox workspace."""
