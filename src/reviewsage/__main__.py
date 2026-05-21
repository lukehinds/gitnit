"""ReviewSage CLI entry point."""

from __future__ import annotations

import os
import sys

import click


@click.command()
@click.option(
    "--repo",
    "-r",
    required=True,
    help="GitHub repository in owner/repo format (e.g. anthropics/nono)",
)
@click.option(
    "--model",
    "-m",
    type=click.Choice(["sonnet", "opus", "haiku"], case_sensitive=False),
    default="sonnet",
    help="Claude model to use for AI analysis",
)
@click.version_option(version="0.1.0", prog_name="ReviewSage")
def main(repo: str, model: str) -> None:
    """ReviewSage - AI-powered TUI for reviewing GitHub pull requests and issues."""
    if "/" not in repo:
        click.echo("Error: --repo must be in owner/repo format", err=True)
        sys.exit(1)

    if not os.environ.get("GITHUB_TOKEN"):
        click.echo("Error: GITHUB_TOKEN environment variable is required", err=True)
        sys.exit(1)

    from reviewsage.app import ReviewSageApp

    app = ReviewSageApp(repo=repo, model=model.lower())
    app.run()


if __name__ == "__main__":
    main()
