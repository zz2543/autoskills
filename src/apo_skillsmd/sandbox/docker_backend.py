"""Future Docker sandbox backend."""

from __future__ import annotations

from apo_skillsmd.sandbox.base import Sandbox
from apo_skillsmd.types import SandboxProfileName


class DockerSandbox(Sandbox):
    """Placeholder that preserves the public interface for later replacement."""

    def __init__(self, profile: SandboxProfileName) -> None:
        super().__init__(profile)

    def setup(self, *, skill=None) -> None:
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def teardown(self) -> None:
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def run_bash(self, command: str, timeout_sec: int):
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def read_file(self, path: str) -> str:
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def write_file(self, path: str, content: str) -> str:
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def list_files(self, path: str = ".") -> list[str]:
        raise NotImplementedError("Docker backend is intentionally deferred.")

    def workspace_root(self):
        raise NotImplementedError("Docker backend is intentionally deferred.")
