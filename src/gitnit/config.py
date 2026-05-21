"""Configuration loading for GitNit."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AIConfig:
    provider: str = "claude-code"
    model: str = "sonnet"
    prompt_version: str = "v2"


@dataclass
class GitHubConfig:
    repo: str = ""
    cache_ttl_seconds: int = 600
    poll_interval_seconds: int = 300


@dataclass
class CacheConfig:
    enabled: bool = True
    dir: str = "~/.cache/gitnit"
    analysis_ttl_days: int = 30
    review_input_ttl_days: int = 14
    max_size_mb: int = 2048


@dataclass
class LocalCodeConfig:
    enabled: bool = False
    mirror_repos: bool = True
    worktrees: bool = True
    ttl_days: int = 7
    max_size_mb: int = 4096


@dataclass
class ContextExcludeConfig:
    patterns: list[str] = field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "node_modules/**",
            "vendor/**",
            "dist/**",
            "build/**",
        ]
    )


@dataclass
class ContextConfig:
    max_files: int = 40
    max_file_bytes: int = 200_000
    max_total_bytes: int = 1_200_000
    include_tests: bool = True
    include_configs: bool = True
    exclude: ContextExcludeConfig = field(default_factory=ContextExcludeConfig)


@dataclass
class GitNitConfig:
    ai: AIConfig = field(default_factory=AIConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    local_code: LocalCodeConfig = field(default_factory=LocalCodeConfig)
    context: ContextConfig = field(default_factory=ContextConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _known_values(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    defaults = cls().__dict__
    return {key: data[key] for key in defaults if key in data}


def _user_config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "gitnit" / "config.toml"


def _project_config_paths(cwd: Path) -> list[Path]:
    return [cwd / "gitnit.toml", cwd / ".gitnit.toml"]


def _config_from_dict(data: dict[str, Any]) -> GitNitConfig:
    ai_data = _section(data, "ai")
    github_data = _section(data, "github")
    cache_data = _section(data, "cache")
    local_code_data = _section(data, "local_code")
    context_data = _section(data, "context")
    exclude_data = _section(context_data, "exclude")
    context_values = _known_values(ContextConfig, context_data)
    context_values.pop("exclude", None)

    return GitNitConfig(
        ai=AIConfig(**{**AIConfig().__dict__, **_known_values(AIConfig, ai_data)}),
        github=GitHubConfig(
            **{**GitHubConfig().__dict__, **_known_values(GitHubConfig, github_data)}
        ),
        cache=CacheConfig(
            **{**CacheConfig().__dict__, **_known_values(CacheConfig, cache_data)}
        ),
        local_code=LocalCodeConfig(
            **{
                **LocalCodeConfig().__dict__,
                **_known_values(LocalCodeConfig, local_code_data),
            }
        ),
        context=ContextConfig(
            **{
                **ContextConfig().__dict__,
                **context_values,
                "exclude": ContextExcludeConfig(
                    **{
                        **ContextExcludeConfig().__dict__,
                        **_known_values(ContextExcludeConfig, exclude_data),
                    }
                ),
            }
        ),
    )


def load_config(config_path: Path | None = None, cwd: Path | None = None) -> GitNitConfig:
    """Load GitNit config from defaults, user config, project config, and explicit path."""
    cwd = cwd or Path.cwd()
    data: dict[str, Any] = {}

    for path in [_user_config_path(), *_project_config_paths(cwd)]:
        if path.exists():
            data = _deep_merge(data, _read_toml(path))

    if config_path is not None:
        data = _deep_merge(data, _read_toml(config_path))

    return _config_from_dict(data)
