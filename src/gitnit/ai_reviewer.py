"""AI reviewer using Claude Agent SDK."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol

from gitnit.cache import (
    get_cached_issue_analysis,
    get_cached_pr_analysis,
    save_issue_analysis,
    save_pr_analysis,
)
from gitnit.models import IssueAnalysis, IssueSeverity, PRAnalysis

if TYPE_CHECKING:
    from gitnit.models import IssueDetail, PRDetail

DEFAULT_PROVIDER = "claude-code"
DEFAULT_MODEL = "sonnet"
DEFAULT_PROMPT_VERSION = "v2"
PR_SCHEMA_VERSION = "pr-analysis-v1"
ISSUE_SCHEMA_VERSION = "issue-analysis-v1"

PR_ANALYSIS_PROMPT = """You are GitNit, an expert code reviewer. Analyze the following pull request and provide your assessment.

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

ISSUE_ANALYSIS_PROMPT = """You are GitNit, an expert at triaging GitHub issues. Analyze the following issue and provide your assessment.

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


def _extract_json(text: str | None) -> dict:
    """Extract JSON from a response that may contain markdown or extra text."""
    if not text:
        return {}

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


def _message_text(message: object) -> str:
    """Extract text from Claude SDK message shapes."""
    result = getattr(message, "result", None)
    if isinstance(result, str) and result:
        return result

    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ""

    text_parts = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            text_parts.append(text)

    return "\n".join(text_parts)


class ReviewerProvider(Protocol):
    """Provider interface for AI-backed review analysis."""

    async def analyze_pr(self, pr_detail: PRDetail, model: str) -> PRAnalysis:
        """Analyze a pull request."""
        ...

    async def analyze_issue(self, issue_detail: IssueDetail, model: str) -> IssueAnalysis:
        """Analyze an issue."""
        ...


class ClaudeCodeProvider:
    """Reviewer provider backed by Claude Agent SDK."""

    async def analyze_pr(self, pr_detail: PRDetail, model: str) -> PRAnalysis:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            return _fallback_pr_analysis(pr_detail)

        diff_truncated = (
            pr_detail.diff[:15000] if len(pr_detail.diff) > 15000 else pr_detail.diff
        )

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
        streamed_text_parts: list[str] = []
        try:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    model=model,
                    allowed_tools=[],
                    max_turns=3,
                ),
            ):
                text = _message_text(message)
                if not text:
                    continue
                if getattr(message, "result", None):
                    result_text = text
                else:
                    streamed_text_parts.append(text)
        except Exception as e:
            return PRAnalysis(
                summary=f"AI analysis failed: {e}",
                review_comment="Unable to generate review comment due to an API error.",
            )

        if not result_text and streamed_text_parts:
            result_text = "\n".join(streamed_text_parts)

        data = _extract_json(result_text)
        if not data:
            return PRAnalysis(
                summary=result_text[:500] if result_text else "No analysis generated.",
                review_comment=result_text if result_text else "No review generated.",
            )

        return _pr_analysis_from_dict(data)

    async def analyze_issue(self, issue_detail: IssueDetail, model: str) -> IssueAnalysis:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            return _fallback_issue_analysis(issue_detail)

        comments_text = (
            "\n\n".join(issue_detail.comments[:10])
            if issue_detail.comments
            else "(no comments)"
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
        streamed_text_parts: list[str] = []
        try:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    model=model,
                    allowed_tools=[],
                    max_turns=3,
                ),
            ):
                text = _message_text(message)
                if not text:
                    continue
                if getattr(message, "result", None):
                    result_text = text
                else:
                    streamed_text_parts.append(text)
        except Exception as e:
            return IssueAnalysis(
                overview=f"AI analysis failed: {e}",
                suggested_fix="Unable to generate fix suggestion due to an API error.",
            )

        if not result_text and streamed_text_parts:
            result_text = "\n".join(streamed_text_parts)

        data = _extract_json(result_text)
        if not data:
            return IssueAnalysis(
                overview=result_text[:500] if result_text else "No analysis generated.",
                suggested_fix="No fix suggestion could be extracted from the response.",
            )

        return _issue_analysis_from_dict(data)


def _get_provider(provider: str) -> ReviewerProvider | None:
    if provider in {"claude-code", "claude"}:
        return ClaudeCodeProvider()
    return None


async def analyze_pr(
    pr_detail: PRDetail,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    repo: str = "",
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> PRAnalysis:
    """Analyze a PR using the selected AI provider. Uses provider-aware cache keys."""
    head_sha = pr_detail.pr.head_sha

    if repo and head_sha:
        cached = get_cached_pr_analysis(
            repo,
            pr_detail.pr.number,
            head_sha,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            schema_version=PR_SCHEMA_VERSION,
        )
        if cached:
            return _pr_analysis_from_dict(cached)

    reviewer = _get_provider(provider)
    if reviewer is None:
        return PRAnalysis(
            summary=f"AI provider '{provider}' is not implemented yet.",
            review_comment=f"Unable to generate review comment with provider '{provider}'.",
        )

    analysis = await reviewer.analyze_pr(pr_detail, model)

    if repo and head_sha:
        save_pr_analysis(
            repo,
            pr_detail.pr.number,
            head_sha,
            asdict(analysis),
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            schema_version=PR_SCHEMA_VERSION,
        )

    return analysis


async def analyze_issue(
    issue_detail: IssueDetail,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    repo: str = "",
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> IssueAnalysis:
    """Analyze an issue using the selected AI provider. Cached by provider/model."""
    if repo:
        cached = get_cached_issue_analysis(
            repo,
            issue_detail.issue.number,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            schema_version=ISSUE_SCHEMA_VERSION,
        )
        if cached:
            return _issue_analysis_from_dict(cached)

    reviewer = _get_provider(provider)
    if reviewer is None:
        return IssueAnalysis(
            overview=f"AI provider '{provider}' is not implemented yet.",
            suggested_fix=f"Unable to generate fix suggestion with provider '{provider}'.",
        )

    analysis = await reviewer.analyze_issue(issue_detail, model)

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
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            schema_version=ISSUE_SCHEMA_VERSION,
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
