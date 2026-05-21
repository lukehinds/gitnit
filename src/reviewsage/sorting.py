"""PR sorting algorithm for ReviewSage."""

from __future__ import annotations

from datetime import UTC, datetime

from reviewsage.models import CIStatus, PRData


def pr_sort_score(pr: PRData) -> float:
    """Compute a composite sort score. Lower score = higher priority in the list.

    Factors:
    - CI status: passing PRs come first (weight: 40%)
    - Size/complexity: smaller PRs rank higher (weight: 35%)
    - Age: older PRs rank slightly higher to avoid stalling (weight: 25%)
    """
    ci_score = {
        CIStatus.PASSING: 0.0,
        CIStatus.PENDING: 0.5,
        CIStatus.UNKNOWN: 0.7,
        CIStatus.FAILING: 1.0,
    }.get(pr.ci_status, 0.7)

    lines = pr.lines_changed
    if lines < 10:
        size_score = 0.0
    elif lines < 50:
        size_score = 0.2
    elif lines < 200:
        size_score = 0.5
    elif lines < 500:
        size_score = 0.8
    else:
        size_score = 1.0

    now = datetime.now(tz=UTC)
    created = pr.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (now - created).days
    age_score = max(0.0, 1.0 - (age_days / 90.0))

    return (ci_score * 0.40) + (size_score * 0.35) + (age_score * 0.25)


def sort_prs(prs: list[PRData]) -> list[PRData]:
    """Sort PRs by composite score (highest priority first)."""
    return sorted(prs, key=pr_sort_score)
