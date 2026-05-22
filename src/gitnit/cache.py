"""LLM analysis cache for GitNit.

PR analyses are cached by provider/model/prompt plus (pr_number, head_sha).
Issue analyses are cached by provider/model/prompt plus issue_number.
List data (PRs, issues) is cached per-repo for instant startup.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from gitnit.models import CIStatus, IssueData, IssueLabel, PRData


@cache
def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    cache = base / "gitnit"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


DEFAULT_ANALYSIS_PROVIDER = "claude-code"
DEFAULT_ANALYSIS_MODEL = "sonnet"
DEFAULT_ANALYSIS_PROMPT_VERSION = "v3"
DEFAULT_PR_SCHEMA_VERSION = "pr-analysis-v1"
DEFAULT_ISSUE_SCHEMA_VERSION = "issue-analysis-v1"


def _pr_cache_path(
    repo: str,
    pr_number: int,
    head_sha: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> Path:
    key = (
        f"pr:{repo}:{pr_number}:{head_sha}:"
        f"{provider}:{model}:{prompt_version}:{schema_version}"
    )
    return _cache_dir() / f"pr-{_key_hash(key)}.json"


def _legacy_pr_cache_path(repo: str, pr_number: int, head_sha: str) -> Path:
    key = f"pr:{repo}:{pr_number}:{head_sha}"
    return _cache_dir() / f"pr-{_key_hash(key)}.json"


def _issue_cache_path(
    repo: str,
    issue_number: int,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> Path:
    key = (
        f"issue:{repo}:{issue_number}:"
        f"{provider}:{model}:{prompt_version}:{schema_version}"
    )
    return _cache_dir() / f"issue-{_key_hash(key)}.json"


def _legacy_issue_cache_path(repo: str, issue_number: int) -> Path:
    key = f"issue:{repo}:{issue_number}"
    return _cache_dir() / f"issue-{_key_hash(key)}.json"


def _list_cache_path(repo: str, kind: str, page: int, extra: str = "") -> Path:
    key = f"list:{kind}:{repo}:{page}:{extra}"
    return _cache_dir() / f"list-{_key_hash(key)}.json"


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _is_fresh(data: dict[str, Any], max_age_seconds: int | None) -> bool:
    if max_age_seconds is None:
        return True

    saved_at = data.get("saved_at")
    if not saved_at:
        return False

    saved = datetime.fromisoformat(saved_at)
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=UTC)
    age = datetime.now(tz=UTC) - saved
    return age.total_seconds() <= max_age_seconds


# --- PR/Issue analysis cache (LLM results) ---


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _analysis_metadata(
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "saved_at": _utc_now_iso(),
    }


def get_cached_pr_analysis(
    repo: str,
    pr_number: int,
    head_sha: str,
    provider: str = DEFAULT_ANALYSIS_PROVIDER,
    model: str = DEFAULT_ANALYSIS_MODEL,
    prompt_version: str = DEFAULT_ANALYSIS_PROMPT_VERSION,
    schema_version: str = DEFAULT_PR_SCHEMA_VERSION,
) -> dict[str, Any] | None:
    """Return cached PR analysis if it exists for the given head SHA."""
    path = _pr_cache_path(
        repo, pr_number, head_sha, provider, model, prompt_version, schema_version
    )
    cached = _read_json(path)
    if cached is not None:
        return cached

    if (
        provider == DEFAULT_ANALYSIS_PROVIDER
        and model == DEFAULT_ANALYSIS_MODEL
        and prompt_version == DEFAULT_ANALYSIS_PROMPT_VERSION
        and schema_version == DEFAULT_PR_SCHEMA_VERSION
    ):
        return _read_json(_legacy_pr_cache_path(repo, pr_number, head_sha))

    return None


def save_pr_analysis(
    repo: str,
    pr_number: int,
    head_sha: str,
    data: dict[str, Any],
    provider: str = DEFAULT_ANALYSIS_PROVIDER,
    model: str = DEFAULT_ANALYSIS_MODEL,
    prompt_version: str = DEFAULT_ANALYSIS_PROMPT_VERSION,
    schema_version: str = DEFAULT_PR_SCHEMA_VERSION,
) -> None:
    """Save PR analysis to cache, keyed by head SHA."""
    path = _pr_cache_path(
        repo, pr_number, head_sha, provider, model, prompt_version, schema_version
    )
    payload = {
        **data,
        "_metadata": _analysis_metadata(provider, model, prompt_version, schema_version),
    }
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(payload))


def get_cached_issue_analysis(
    repo: str,
    issue_number: int,
    provider: str = DEFAULT_ANALYSIS_PROVIDER,
    model: str = DEFAULT_ANALYSIS_MODEL,
    prompt_version: str = DEFAULT_ANALYSIS_PROMPT_VERSION,
    schema_version: str = DEFAULT_ISSUE_SCHEMA_VERSION,
) -> dict[str, Any] | None:
    """Return cached issue analysis if it exists."""
    path = _issue_cache_path(
        repo, issue_number, provider, model, prompt_version, schema_version
    )
    cached = _read_json(path)
    if cached is not None:
        return cached

    if (
        provider == DEFAULT_ANALYSIS_PROVIDER
        and model == DEFAULT_ANALYSIS_MODEL
        and prompt_version == DEFAULT_ANALYSIS_PROMPT_VERSION
        and schema_version == DEFAULT_ISSUE_SCHEMA_VERSION
    ):
        return _read_json(_legacy_issue_cache_path(repo, issue_number))

    return None


def save_issue_analysis(
    repo: str,
    issue_number: int,
    data: dict[str, Any],
    provider: str = DEFAULT_ANALYSIS_PROVIDER,
    model: str = DEFAULT_ANALYSIS_MODEL,
    prompt_version: str = DEFAULT_ANALYSIS_PROMPT_VERSION,
    schema_version: str = DEFAULT_ISSUE_SCHEMA_VERSION,
) -> None:
    """Save issue analysis to cache (permanent)."""
    path = _issue_cache_path(
        repo, issue_number, provider, model, prompt_version, schema_version
    )
    payload = {
        **data,
        "_metadata": _analysis_metadata(provider, model, prompt_version, schema_version),
    }
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(payload))


# --- List data cache (PR/issue lists for instant startup) ---


def _pr_to_dict(pr: PRData) -> dict[str, Any]:
    return {
        "number": pr.number,
        "title": pr.title,
        "author": pr.author,
        "is_dependabot": pr.is_dependabot,
        "additions": pr.additions,
        "deletions": pr.deletions,
        "changed_files": pr.changed_files,
        "ci_status": pr.ci_status.value,
        "created_at": pr.created_at.isoformat(),
        "updated_at": pr.updated_at.isoformat(),
        "head_sha": pr.head_sha,
        "body": pr.body,
        "labels": pr.labels,
    }


def _dict_to_pr(d: dict[str, Any]) -> PRData:
    return PRData(
        number=d["number"],
        title=d["title"],
        author=d["author"],
        is_dependabot=d["is_dependabot"],
        additions=d["additions"],
        deletions=d["deletions"],
        changed_files=d["changed_files"],
        ci_status=CIStatus(d.get("ci_status", "unknown")),
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
        head_sha=d.get("head_sha", ""),
        body=d.get("body", ""),
        labels=d.get("labels", []),
    )


def _issue_to_dict(issue: IssueData) -> dict[str, Any]:
    return {
        "number": issue.number,
        "title": issue.title,
        "author": issue.author,
        "label": issue.label.value,
        "label_raw": issue.label_raw,
        "state": issue.state,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat(),
        "body": issue.body,
        "comment_count": issue.comment_count,
    }


def _dict_to_issue(d: dict[str, Any]) -> IssueData:
    return IssueData(
        number=d["number"],
        title=d["title"],
        author=d["author"],
        label=IssueLabel(d.get("label", "other")),
        label_raw=d.get("label_raw", ""),
        state=d["state"],
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
        body=d.get("body", ""),
        comment_count=d.get("comment_count", 0),
    )


def get_cached_pr_list(
    repo: str, page: int = 0, max_age_seconds: int | None = None
) -> tuple[list[PRData], int] | None:
    """Return cached PR list for a repo page, or None if not cached."""
    path = _list_cache_path(repo, "prs", page)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not _is_fresh(data, max_age_seconds):
            return None
        prs = [_dict_to_pr(d) for d in data["items"]]
        return prs, data["total"]
    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError):
        return None


def save_pr_list(repo: str, page: int, prs: list[PRData], total: int) -> None:
    """Save PR list to cache."""
    path = _list_cache_path(repo, "prs", page)
    data = {
        "items": [_pr_to_dict(pr) for pr in prs],
        "total": total,
        "saved_at": _utc_now_iso(),
    }
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(data))


def get_cached_issue_list(
    repo: str,
    page: int = 0,
    direction: str = "desc",
    max_age_seconds: int | None = None,
) -> tuple[list[IssueData], int] | None:
    """Return cached issue list for a repo page, or None if not cached."""
    path = _list_cache_path(repo, "issues", page, extra=direction)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not _is_fresh(data, max_age_seconds):
            return None
        issues = [_dict_to_issue(d) for d in data["items"]]
        return issues, data["total"]
    except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError):
        return None


def save_issue_list(
    repo: str, page: int, issues: list[IssueData], total: int, direction: str = "desc"
) -> None:
    """Save issue list to cache."""
    path = _list_cache_path(repo, "issues", page, extra=direction)
    data = {
        "items": [_issue_to_dict(i) for i in issues],
        "total": total,
        "saved_at": _utc_now_iso(),
    }
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(data))
