"""Named sandbox profiles used by the subprocess backend."""

from __future__ import annotations

from pydantic import BaseModel, Field

from apo_skillsmd.types import SandboxProfileName


class SandboxProfileConfig(BaseModel):
    """Limits and capabilities attached to a profile."""

    profile: SandboxProfileName
    description: str
    network_access: bool = False
    writable_roots: list[str] = Field(default_factory=lambda: ["."])
    cpu_time_sec: int = 30
    memory_mb: int = 1024
    best_effort_only: bool = False


PROFILE_CONFIGS: dict[SandboxProfileName, SandboxProfileConfig] = {
    SandboxProfileName.OFFLINE_LOCAL: SandboxProfileConfig(
        profile=SandboxProfileName.OFFLINE_LOCAL,
        description="Best-effort local offline execution with tempdir jail.",
        network_access=False,
        writable_roots=["."],
        cpu_time_sec=30,
        memory_mb=1024,
        best_effort_only=True,
    ),
    SandboxProfileName.OFFLINE_EXTENDED: SandboxProfileConfig(
        profile=SandboxProfileName.OFFLINE_EXTENDED,
        description="Longer offline budget for expensive local workflows.",
        network_access=False,
        writable_roots=["."],
        cpu_time_sec=90,
        memory_mb=2048,
        best_effort_only=True,
    ),
    SandboxProfileName.NETWORK_WHITELIST: SandboxProfileConfig(
        profile=SandboxProfileName.NETWORK_WHITELIST,
        description="Network-enabled profile intended for future whitelist enforcement.",
        network_access=True,
        writable_roots=["."],
        cpu_time_sec=90,
        memory_mb=2048,
        best_effort_only=True,
    ),
}


def get_profile_config(profile: SandboxProfileName) -> SandboxProfileConfig:
    """Look up the config attached to a named profile."""

    return PROFILE_CONFIGS[profile]
