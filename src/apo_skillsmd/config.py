"""Application settings and configuration loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from apo_skillsmd.types import ProviderName, SandboxProfileName


class LLMSettings(BaseModel):
    """Runtime settings for the LLM backend."""

    provider: ProviderName = ProviderName.MINIMAX
    model: str = "MiniMax-M2.1"
    temperature: float = 0.2
    max_tokens: int = 2048
    base_url: str | None = "https://api.minimax.io/v1"
    timeout_sec: int = 60
    use_cache: bool = True
    cache_dir: str = ".cache/llm"


class SandboxSettings(BaseModel):
    """Execution limits for the active sandbox backend."""

    profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL
    max_steps: int = 8
    command_timeout_sec: int = 30
    workspace_root: str = ".sandbox"
    cpu_time_sec: int = 30
    memory_mb: int = 1024
    max_output_chars: int = 6000


class PathSettings(BaseModel):
    """Common repository-relative paths."""

    data_dir: str = "data"
    results_dir: str = "results"
    baseline_dir: str = "data/baselines"
    pool_dir: str = "data/skill_pool"
    skillsbench_dir: str = "data/skillsbench"
    mutation_meta_skill_dir: str = "meta_skills/skill_mutator"


class EvolutionSettings(BaseModel):
    """Main evolution loop configuration."""

    population_size: int = 6
    generations: int = 2
    retrieval_top_k: int = 8
    max_llm_generated_ratio: float = 0.3
    stagnation_window: int = 3
    escape_injections: int = 2
    enable_trace: bool = True
    enable_crossover: bool = True
    enable_pareto: bool = True
    enable_escape: bool = False  # disabled: escape injects synthetic seeds only; re-enable after Lamarckian back-inference is implemented


class ExperimentSettings(BaseModel):
    """Experiment orchestration defaults."""

    default_task_glob: str = "data/skillsbench/tasks/*.json"
    default_output_dir: str = "results/default"
    min_test_cases: int = 3


class AppSettings(BaseSettings):
    """Top-level application settings sourced from `.env` and YAML."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    experiments: ExperimentSettings = Field(default_factory=ExperimentSettings)

    minimax_api_key: str | None = Field(default=None, validation_alias="MINIMAX_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    qwen_api_key: str | None = Field(default=None, validation_alias="QWEN_API_KEY")

    minimax_base_url: str | None = Field(default=None, validation_alias="MINIMAX_BASE_URL")
    minimax_model: str | None = Field(default=None, validation_alias="MINIMAX_MODEL")
    experiment_name: str = "default"

    def api_key_for_provider(self, provider: ProviderName) -> str | None:
        """Return the configured API key for the active provider."""

        mapping = {
            ProviderName.MINIMAX: self.minimax_api_key,
            ProviderName.OPENAI: self.openai_api_key,
            ProviderName.ANTHROPIC: self.anthropic_api_key,
            ProviderName.GEMINI: self.gemini_api_key,
            ProviderName.QWEN: self.qwen_api_key,
            ProviderName.MOCK: None,
        }
        return mapping[provider]

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a repository-relative path from the current working directory."""

        return Path(relative_path).expanduser().resolve()


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""

    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return loaded


def _merge_dicts(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries while preserving nested settings."""

    merged = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    """Load settings from environment and optionally merge a YAML config on top."""

    settings = AppSettings()
    if config_path is None:
        if settings.minimax_base_url:
            settings.llm.base_url = settings.minimax_base_url
        if settings.minimax_model:
            settings.llm.model = settings.minimax_model
        return settings

    path = Path(config_path)
    raw = load_yaml_file(path)
    if "extends" in raw:
        parent = load_yaml_file((path.parent / raw.pop("extends")).resolve())
        raw = _merge_dicts(parent, raw)

    merged = _merge_dicts(settings.model_dump(), raw)
    merged_settings = AppSettings.model_validate(merged)
    if merged_settings.minimax_base_url:
        merged_settings.llm.base_url = merged_settings.minimax_base_url
    if merged_settings.minimax_model:
        merged_settings.llm.model = merged_settings.minimax_model
    return merged_settings
