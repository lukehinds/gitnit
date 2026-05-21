"""AI reviewer using Claude Agent SDK."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from reviewsage.cache import (
    get_cached_issue_analysis,
    get_cached_pr_analysis,
    save_issue_analysis,
    save_pr_analysis,
)
from reviewsage.models import IssueAnalysis, IssueSeverity, PRAnalysis

if TYPE_CHECKING:
    from reviewsage.models import IssueDetail, PRDetail

PR_ANALYSIS_PROMPT = """You are ReviewSage, an expert code reviewer. Analyze the following pull request and provide your assessment.

## Pull Request Information
- **Title:** {title}
- **Author:** {author}
- **PR #{number}**
- **Files changed:** {changed_files}
- **Lines added:** {additions} / **Lines deleted:** {deletions}

## PR Description
{body}

## Changed Files
{files}

## Diff
{diff}

---

Respond with a JSON object containing exactly these fields (no markdown, just raw JSON):

{{
  "summary": "A brief 2-3 sentence summary of what this PR achieves, in plain language.",
  "security_risks": "Assessment of any security implications. If none, say 'No significant security risks identified.'",
  "code_quality": "Brief assessment of code quality, patterns, and maintainability.",
  "risk_level": "One of: Low, Medium, High, Critical",
  "disruption_assessment": "How likely is this PR to break existing functionality? Consider scope of changes, test coverage implied, and areas affected.",
  "backwards_compatibility": "Does this PR break any APIs, configs, or user-facing behavior? Would it require a major semver bump?",
  "semver_impact": "One of: patch, minor, major - based on backwards compatibility analysis.",
  "review_comment": "Write a friendly, professional review comment as if you are the maintainer. Be approachable but technical. Address the author by their username. Start with acknowledgment of the work, then provide specific feedback, and end with next steps or approval suggestion. Do NOT use markdown headers. Use plain paragraphs."
}}
"""

ISSUE_ANALYSIS_PROMPT = """You are ReviewSage, an expert at triaging GitHub issues. Analyze the following issue and provide your assessment.

## Issue Information
- **Title:** {title}
- **Author:** {author}
- **Issue #{number}**
- **Labels:** {labels}

## Issue Body
{body}

## Comments
{comments}

---

Respond with a JSON object containing exactly these fields (no markdown, just raw JSON):

{{
  "severity": "One of: Critical, High, Medium, Low, Info",
  "overview": "A clear, simplified explanation of the issue. What is happening, when does it occur, and who is affected? Write for someone who hasn't read the issue.",
  "suspected_cause": "Based on the information provided, what do you believe is the root cause? If unclear, state what investigation would be needed.",
  "suggested_fix": "Describe the fix approach in clear, actionable terms. Write this so someone could copy it and give it to a coding assistant as instructions. Include specific file paths or components if you can infer them. Be concrete about what code changes are needed."
}}
"""


def _extract_json(text: str) -> dict:
    """Extract JSON from a response that may contain markdown or extra text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


def _pr_analysis_from_dict(data: dict) -> PRAnalysis:
    return PRAnalysis(
        summary=data.get("summary", ""),
        security_risks=data.get("security_risks", ""),
        code_quality=data.get("code_quality", ""),
        risk_level=data.get("risk_level", "Unknown"),
        disruption_assessment=data.get("disruption_assessment", ""),
        backwards_compatibility=data.get("backwards_compatibility", ""),
        semver_impact=data.get("semver_impact", ""),
        review_comment=data.get("review_comment", ""),
    )


def _issue_analysis_from_dict(data: dict) -> IssueAnalysis:
    severity_map = {
        "critical": IssueSeverity.CRITICAL,
        "high": IssueSeverity.HIGH,
        "medium": IssueSeverity.MEDIUM,
        "low": IssueSeverity.LOW,
        "info": IssueSeverity.INFO,
    }
    return IssueAnalysis(
        severity=severity_map.get(data.get("severity", "").lower(), IssueSeverity.INFO),
        overview=data.get("overview", ""),
        suspected_cause=data.get("suspected_cause", ""),
        suggested_fix=data.get("suggested_fix", ""),
    )


async def analyze_pr(pr_detail: PRDetail, model: str = "sonnet", repo: str = "") -> PRAnalysis:
    """Analyze a PR using Claude Agent SDK. Uses cache keyed by head SHA."""
    head_sha = pr_detail.pr.head_sha

    if repo and head_sha:
        cached = get_cached_pr_analysis(repo, pr_detail.pr.number, head_sha)
        if cached:
            return _pr_analysis_from_dict(cached)

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return _fallback_pr_analysis(pr_detail)

    diff_truncated = pr_detail.diff[:15000] if len(pr_detail.diff) > 15000 else pr_detail.diff

    prompt = PR_ANALYSIS_PROMPT.format(
        title=pr_detail.pr.title,
        author=pr_detail.pr.author,
        number=pr_detail.pr.number,
        changed_files=pr_detail.pr.changed_files,
        additions=pr_detail.pr.additions,
        deletions=pr_detail.pr.deletions,
        body=pr_detail.pr.body or "(no description)",
        files="\n".join(f"- {f}" for f in pr_detail.files),
        diff=diff_truncated,
    )

    result_text = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model,
                allowed_tools=[],
                max_turns=1,
            ),
        ):
            if hasattr(message, "result"):
                result_text = message.result
    except Exception as e:
        return PRAnalysis(
            summary=f"AI analysis failed: {e}",
            review_comment="Unable to generate review comment due to an API error.",
        )

    data = _extract_json(result_text)
    if not data:
        return PRAnalysis(
            summary=result_text[:500] if result_text else "No analysis generated.",
            review_comment=result_text if result_text else "No review generated.",
        )

    analysis = _pr_analysis_from_dict(data)

    if repo and head_sha:
        save_pr_analysis(repo, pr_detail.pr.number, head_sha, asdict(analysis))

    return analysis


async def analyze_issue(
    issue_detail: IssueDetail, model: str = "sonnet", repo: str = ""
) -> IssueAnalysis:
    """Analyze an issue using Claude Agent SDK. Cached permanently by issue number."""
    if repo:
        cached = get_cached_issue_analysis(repo, issue_detail.issue.number)
        if cached:
            return _issue_analysis_from_dict(cached)

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return _fallback_issue_analysis(issue_detail)

    comments_text = (
        "\n\n".join(issue_detail.comments[:10]) if issue_detail.comments else "(no comments)"
    )

    prompt = ISSUE_ANALYSIS_PROMPT.format(
        title=issue_detail.issue.title,
        author=issue_detail.issue.author,
        number=issue_detail.issue.number,
        labels=issue_detail.issue.label_raw or "none",
        body=issue_detail.issue.body or "(no description)",
        comments=comments_text,
    )

    result_text = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                model=model,
                allowed_tools=[],
                max_turns=1,
            ),
        ):
            if hasattr(message, "result"):
                result_text = message.result
    except Exception as e:
        return IssueAnalysis(
            overview=f"AI analysis failed: {e}",
            suggested_fix="Unable to generate fix suggestion due to an API error.",
        )

    data = _extract_json(result_text)
    if not data:
        return IssueAnalysis(
            overview=result_text[:500] if result_text else "No analysis generated.",
            suggested_fix="No fix suggestion could be extracted from the response.",
        )

    analysis = _issue_analysis_from_dict(data)

    if repo:
        save_issue_analysis(
            repo,
            issue_detail.issue.number,
            {
                "severity": analysis.severity.value,
                "overview": analysis.overview,
                "suspected_cause": analysis.suspected_cause,
                "suggested_fix": analysis.suggested_fix,
            },
        )

    return analysis


def _fallback_pr_analysis(pr_detail: PRDetail) -> PRAnalysis:
    """Fallback when Claude Agent SDK is not available."""
    return PRAnalysis(
        summary=(
            f"PR #{pr_detail.pr.number}: {pr_detail.pr.title}\n\n"
            f"Changes {pr_detail.pr.changed_files} files "
            f"(+{pr_detail.pr.additions}/-{pr_detail.pr.deletions} lines).\n\n"
            "Install claude-agent-sdk for AI-powered analysis."
        ),
        security_risks="AI analysis unavailable - install claude-agent-sdk",
        code_quality="AI analysis unavailable - install claude-agent-sdk",
        risk_level="Unknown",
        disruption_assessment="AI analysis unavailable",
        backwards_compatibility="AI analysis unavailable",
        semver_impact="unknown",
        review_comment="AI review comment unavailable - install claude-agent-sdk",
    )


def _fallback_issue_analysis(issue_detail: IssueDetail) -> IssueAnalysis:
    """Fallback when Claude Agent SDK is not available."""
    body_preview = issue_detail.issue.body[:300] if issue_detail.issue.body else "No description."
    return IssueAnalysis(
        overview=(
            f"Issue #{issue_detail.issue.number}: {issue_detail.issue.title}\n\n"
            f"{body_preview}\n\n"
            "Install claude-agent-sdk for AI-powered analysis."
        ),
        suspected_cause="AI analysis unavailable - install claude-agent-sdk",
        suggested_fix="AI analysis unavailable - install claude-agent-sdk",
    )
