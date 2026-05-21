"""GitHub API client wrapper."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from github import Github
from github.GithubException import GithubException

from reviewsage.models import CIStatus, IssueData, IssueDetail, IssueLabel, PRData, PRDetail

if TYPE_CHECKING:
    from github.PullRequest import PullRequest
    from github.Repository import Repository


class GitHubClientError(Exception):
    pass


class GitHubClient:
    def __init__(self, repo_slug: str) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            msg = "GITHUB_TOKEN environment variable is required"
            raise GitHubClientError(msg)

        self._gh = Github(token)
        try:
            self._repo: Repository = self._gh.get_repo(repo_slug)
        except GithubException as e:
            msg = f"Failed to access repository '{repo_slug}': {e.data.get('message', str(e))}"
            raise GitHubClientError(msg) from e

    @property
    def repo_name(self) -> str:
        return self._repo.full_name

    def _get_ci_status(self, pr: PullRequest) -> CIStatus:
        try:
            commit = self._repo.get_commit(pr.head.sha)
            check_runs = list(commit.get_check_runs())
            if not check_runs:
                combined = commit.get_combined_status()
                if combined.state == "success":
                    return CIStatus.PASSING
                if combined.state == "failure":
                    return CIStatus.FAILING
                if combined.state == "pending":
                    return CIStatus.PENDING
                return CIStatus.UNKNOWN

            all_passed = all(cr.conclusion == "success" for cr in check_runs)
            any_failed = any(cr.conclusion in ("failure", "cancelled") for cr in check_runs)
            any_pending = any(cr.status in ("queued", "in_progress") for cr in check_runs)

            if all_passed:
                return CIStatus.PASSING
            if any_failed:
                return CIStatus.FAILING
            if any_pending:
                return CIStatus.PENDING
            return CIStatus.UNKNOWN
        except GithubException:
            return CIStatus.UNKNOWN

    def _pr_to_data(self, pr: PullRequest, fetch_ci: bool = True) -> PRData:
        author = pr.user.login if pr.user else "unknown"
        is_bot = "dependabot" in author.lower() or "bot" in (pr.user.type or "").lower()
        ci = self._get_ci_status(pr) if fetch_ci else CIStatus.UNKNOWN

        return PRData(
            number=pr.number,
            title=pr.title,
            author=author,
            is_dependabot=is_bot,
            additions=pr.additions,
            deletions=pr.deletions,
            changed_files=pr.changed_files,
            ci_status=ci,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            head_sha=pr.head.sha if pr.head else "",
            body=pr.body or "",
            labels=[label.name for label in pr.labels],
        )

    def get_open_pr_count(self) -> int:
        """Return the total number of open PRs (lightweight API call)."""
        try:
            return self._repo.get_pulls(state="open").totalCount
        except GithubException:
            return -1

    def get_open_issue_count(self) -> int:
        """Return the total number of open issues (includes PRs in GitHub API)."""
        try:
            return self._repo.get_issues(state="open").totalCount
        except GithubException:
            return -1

    def list_prs(self, page: int = 0, per_page: int = 15) -> tuple[list[PRData], int]:
        """Return a page of open PRs and the total count.

        CI status is not fetched here to avoid N+1 API calls.
        """
        prs = self._repo.get_pulls(state="open", sort="updated", direction="desc")
        total = prs.totalCount
        page_items = prs.get_page(page)
        results = [self._pr_to_data(pr, fetch_ci=False) for pr in page_items[:per_page]]
        return results, total

    def get_pr_detail(self, number: int) -> PRDetail:
        pr = self._repo.get_pull(number)
        data = self._pr_to_data(pr, fetch_ci=True)

        pr_files = list(pr.get_files())
        files = [f.filename for f in pr_files]
        diff_parts = [f"--- {f.filename}\n{f.patch}" for f in pr_files if f.patch]

        comments = [f"{c.user.login}: {c.body}" for c in pr.get_issue_comments()]

        return PRDetail(
            pr=data, diff="\n\n".join(diff_parts), files=files, review_comments=comments
        )

    def get_pr_summary(self, number: int) -> PRDetail:
        """Get PR metadata without the expensive diff/files fetch (single API call)."""
        pr = self._repo.get_pull(number)
        data = self._pr_to_data(pr, fetch_ci=True)
        return PRDetail(pr=data)

    def get_pr_head_sha(self, number: int) -> str:
        """Get just the head SHA for a PR (single API call)."""
        try:
            pr = self._repo.get_pull(number)
            return pr.head.sha if pr.head else ""
        except GithubException:
            return ""

    def list_issues(
        self, page: int = 0, per_page: int = 15, sort: str = "created", direction: str = "desc"
    ) -> tuple[list[IssueData], int]:
        """Return a page of open issues (excluding PRs) and the total count."""
        issues = self._repo.get_issues(state="open", sort=sort, direction=direction)
        total = issues.totalCount
        page_items = issues.get_page(page)
        results = []
        for issue in page_items[:per_page]:
            if issue.pull_request is not None:
                continue
            labels = [label.name for label in issue.labels]
            primary_label = IssueLabel.OTHER
            label_raw = ""
            if labels:
                label_raw = labels[0]
                primary_label = IssueLabel.from_github_label(labels[0])
            results.append(
                IssueData(
                    number=issue.number,
                    title=issue.title,
                    author=issue.user.login if issue.user else "unknown",
                    label=primary_label,
                    label_raw=label_raw,
                    state=issue.state,
                    created_at=issue.created_at,
                    updated_at=issue.updated_at,
                    body=issue.body or "",
                    comment_count=issue.comments,
                )
            )
        return results, total

    def get_issue_summary(self, number: int) -> IssueDetail:
        """Get issue metadata without fetching comments (single API call)."""
        issue = self._repo.get_issue(number)
        labels = [label.name for label in issue.labels]
        primary_label = IssueLabel.OTHER
        label_raw = ""
        if labels:
            label_raw = labels[0]
            primary_label = IssueLabel.from_github_label(labels[0])

        data = IssueData(
            number=issue.number,
            title=issue.title,
            author=issue.user.login if issue.user else "unknown",
            label=primary_label,
            label_raw=label_raw,
            state=issue.state,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            body=issue.body or "",
            comment_count=issue.comments,
        )
        return IssueDetail(issue=data)

    def get_issue_detail(self, number: int) -> IssueDetail:
        issue = self._repo.get_issue(number)
        labels = [label.name for label in issue.labels]
        primary_label = IssueLabel.OTHER
        label_raw = ""
        if labels:
            label_raw = labels[0]
            primary_label = IssueLabel.from_github_label(labels[0])

        data = IssueData(
            number=issue.number,
            title=issue.title,
            author=issue.user.login if issue.user else "unknown",
            label=primary_label,
            label_raw=label_raw,
            state=issue.state,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            body=issue.body or "",
            comment_count=issue.comments,
        )

        comments = []
        for comment in issue.get_comments():
            comments.append(f"{comment.user.login}: {comment.body}")

        return IssueDetail(issue=data, comments=comments)
