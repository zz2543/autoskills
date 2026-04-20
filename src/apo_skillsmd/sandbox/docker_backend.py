"""Docker-based sandbox backend."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from apo_skillsmd.sandbox.base import CommandResult, Sandbox
from apo_skillsmd.sandbox.profiles import get_profile_config
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.types import SandboxProfileName


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class DockerSandbox(Sandbox):
    """Ephemeral Docker-backed sandbox.

    Each instance mounts a host workspace directory to /workspace inside the
    container and runs commands via ``docker exec``.  Network access is
    controlled by the profile: offline profiles use ``--network=none``.

    Requirements: Docker daemon must be running and the ``docker`` CLI
    available on PATH.  Use ``DockerSandbox.is_available()`` to check.
    """

    def __init__(
        self,
        profile: SandboxProfileName,
        *,
        image: str = "python:3.11-slim",
        base_dir: str | Path | None = None,
        max_output_chars: int = 6000,
        container_workdir: str = "/workspace",
    ) -> None:
        super().__init__(profile)
        self.profile_config = get_profile_config(profile)
        self._image = image
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        self._max_output_chars = max_output_chars
        self._container_workdir = container_workdir
        self._container_id: str | None = None
        self._workspace: Path | None = None

    @staticmethod
    def is_available() -> bool:
        return _docker_available()

    def setup(self, *, skill: Skill | None = None) -> None:
        if not self.is_available():
            raise RuntimeError(
                "Docker is not available. "
                "Make sure the Docker daemon is running and 'docker' is on PATH."
            )
        base_dir = self._base_dir or Path(tempfile.mkdtemp(prefix="apo_docker_"))
        base_dir.mkdir(parents=True, exist_ok=True)
        self._workspace = base_dir

        if skill is not None:
            dump_skill(skill, base_dir)

        network_flag = "--network=none" if not self.profile_config.network_access else "--network=bridge"
        mem_limit = f"{self.profile_config.memory_mb}m"
        run_cmd = [
            "docker", "run",
            "-d",
            "--rm",
            network_flag,
            f"--memory={mem_limit}",
            "--cpus=1",
            "-v", f"{base_dir}:{self._container_workdir}",
            "-w", self._container_workdir,
            self._image,
            "sleep", "infinity",
        ]
        result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start Docker container: {result.stderr.strip()}"
            )
        self._container_id = result.stdout.strip()

    def teardown(self) -> None:
        if self._container_id:
            subprocess.run(
                ["docker", "stop", "--time=5", self._container_id],
                capture_output=True,
                timeout=15,
            )
            self._container_id = None
        if self._workspace and self._base_dir is None:
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None

    def workspace_root(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("DockerSandbox has not been set up.")
        return self._workspace

    def _snapshot(self) -> dict[str, str]:
        from hashlib import sha256

        root = self.workspace_root()
        snapshot: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            snapshot[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
        return snapshot

    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        if not self._container_id:
            raise RuntimeError("DockerSandbox has no running container. Call setup() first.")
        before = self._snapshot()
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["docker", "exec", self._container_id, "/bin/sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout_sec + 5,
            )
            timed_out = False
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            stdout = ""
            stderr = "command timed out"

        after = self._snapshot()
        changed_files = sorted(
            path for path, digest in after.items()
            if before.get(path) != digest or path not in before
        )
        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout[: self._max_output_chars],
            stderr=stderr[: self._max_output_chars],
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
            changed_files=changed_files,
        )

    def read_file(self, path: str) -> str:
        host_path = self.workspace_root() / path
        return host_path.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        host_path = self.workspace_root() / path
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.write_text(content, encoding="utf-8")
        return path

    def list_files(self, path: str = ".") -> list[str]:
        root = self.workspace_root()
        target = (root / path).resolve()
        if target.is_file():
            return [target.relative_to(root).as_posix()]
        return sorted(
            child.relative_to(root).as_posix()
            for child in target.rglob("*")
            if child.is_file()
        )
