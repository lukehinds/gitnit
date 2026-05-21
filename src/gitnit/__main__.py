"""GitNit CLI entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click


@click.command()
@click.option(
    "--repo",
    "-r",
    required=False,
    help="GitHub repository in owner/repo format (e.g. anthropics/nono)",
)
@click.option(
    "--provider",
    "-p",
    default=None,
    help="AI provider to use for analysis (default: claude-code)",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Model to use for AI analysis",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a gitnit.toml config file",
)
@click.version_option(version="0.1.0", prog_name="GitNit")
def main(
    repo: str | None,
    provider: str | None,
    model: str | None,
    config_path: Path | None,
) -> None:
    """GitNit - AI-powered TUI for reviewing GitHub pull requests and issues."""
    from gitnit.config import load_config

    config = load_config(config_path=config_path)
    repo = repo or config.github.repo
    provider = provider or config.ai.provider
    model = model or config.ai.model

    if not repo:
        click.echo("Error: --repo is required unless github.repo is set in config", err=True)
        sys.exit(1)

    if "/" not in repo:
        click.echo("Error: --repo must be in owner/repo format", err=True)
        sys.exit(1)

    if not os.environ.get("GITHUB_TOKEN"):
        click.echo("Error: GITHUB_TOKEN environment variable is required", err=True)
        sys.exit(1)

    from gitnit.app import GitNitApp

    app = GitNitApp(
        repo=repo,
        provider=provider.lower(),
        model=model,
        prompt_version=config.ai.prompt_version,
        cache_ttl_seconds=config.github.cache_ttl_seconds,
        poll_interval_seconds=config.github.poll_interval_seconds,
    )
    app.run()


if __name__ == "__main__":
    main()
