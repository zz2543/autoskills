"""Default tempdir-based sandbox backend."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - not available on some platforms
    resource = None

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.sandbox.base import CommandResult, Sandbox
from apo_skillsmd.sandbox.profiles import get_profile_config
from apo_skillsmd.types import SandboxProfileName


class SubprocessSandbox(Sandbox):
    """Simple sandbox that runs commands inside a temporary directory.

    On macOS, network restrictions are best-effort only. The implementation
    still keeps workspace isolation and resource limits, which are the most
    important guarantees for repeatable experiments in this repository.
    """

    def __init__(
        self,
        profile: SandboxProfileName,
        *,
        base_dir: str | Path | None = None,
        max_output_chars: int = 6000,
    ) -> None:
        super().__init__(profile)
        self.profile_config = get_profile_config(profile)
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        self._workspace: Path | None = None
        self._max_output_chars = max_output_chars

    def setup(self, *, skill: Skill | None = None) -> None:
        base_dir = self._base_dir or Path(tempfile.mkdtemp(prefix="apo_skillsmd_"))
        base_dir.mkdir(parents=True, exist_ok=True)
        self._workspace = base_dir
        if skill is not None:
            dump_skill(skill, base_dir)

    def teardown(self) -> None:
        if self._workspace is None or self._base_dir is not None:
            return
        shutil.rmtree(self._workspace, ignore_errors=True)
        self._workspace = None

    def workspace_root(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("Sandbox has not been set up.")
        return self._workspace

    def _resolve(self, relative_path: str) -> Path:
        root = self.workspace_root().resolve()
        candidate = (root / relative_path).resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(f"Path escapes sandbox root: {relative_path}")
        return candidate

    def _snapshot(self) -> dict[str, str]:
        root = self.workspace_root()
        snapshot: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            snapshot[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
        return snapshot

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if not self.profile_config.network_access:
            # This is best-effort only. True isolation requires the future Docker backend.
            env.update(
                {
                    "http_proxy": "",
                    "https_proxy": "",
                    "HTTP_PROXY": "",
                    "HTTPS_PROXY": "",
                    "ALL_PROXY": "",
                    "NO_PROXY": "*",
                }
            )
        return env

    def _preexec_limits(self) -> None:
        if resource is None:
            return
        cpu = self.profile_config.cpu_time_sec
        memory = self.profile_config.memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        except (OSError, ValueError):
            pass
        if sys.platform != "darwin":
            try:
                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            except (OSError, ValueError):
                pass

    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        before = self._snapshot()
        start = time.monotonic()
        process = subprocess.Popen(
            ["/bin/sh", "-lc", command],
            cwd=self.workspace_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self._build_env(),
            preexec_fn=self._preexec_limits if resource else None,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_sec)
            timed_out = False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            timed_out = True

        after = self._snapshot()
        changed_files = sorted(
            path for path, digest in after.items() if before.get(path) != digest or path not in before
        )
        return CommandResult(
            command=command,
            exit_code=process.returncode or 0,
            stdout=stdout[: self._max_output_chars],
            stderr=stderr[: self._max_output_chars],
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
            changed_files=changed_files,
        )

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        file_path = self._resolve(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return path

    def list_files(self, path: str = ".") -> list[str]:
        root = self._resolve(path)
        workspace_root = self.workspace_root().resolve()
        if root.is_file():
            return [root.resolve().relative_to(workspace_root).as_posix()]
        return sorted(
            child.resolve().relative_to(workspace_root).as_posix()
            for child in root.rglob("*")
            if child.is_file()
        )
