"""Data models for ReviewSage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class CIStatus(Enum):
    PASSING = "passing"
    FAILING = "failing"
    PENDING = "pending"
    UNKNOWN = "unknown"


class PRSize(Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"

    @classmethod
    def from_lines(cls, lines_changed: int) -> PRSize:
        if lines_changed < 10:
            return cls.XS
        if lines_changed < 50:
            return cls.S
        if lines_changed < 200:
            return cls.M
        if lines_changed < 500:
            return cls.L
        return cls.XL


class IssueSeverity(Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


class IssueLabel(Enum):
    BUG = "bug"
    QUESTION = "question"
    ENHANCEMENT = "enhancement"
    FEATURE = "feature"
    OTHER = "other"

    @classmethod
    def from_github_label(cls, label_name: str) -> IssueLabel:
        normalized = label_name.lower().strip()
        for member in cls:
            if member.value in normalized:
                return member
        if "feat" in normalized:
            return cls.FEATURE
        return cls.OTHER


@dataclass
class PRData:
    number: int
    title: str
    author: str
    is_dependabot: bool
    additions: int
    deletions: int
    changed_files: int
    ci_status: CIStatus
    created_at: datetime
    updated_at: datetime
    head_sha: str = ""
    body: str = ""
    labels: list[str] = field(default_factory=list)

    @property
    def lines_changed(self) -> int:
        return self.additions + self.deletions

    @property
    def size(self) -> PRSize:
        return PRSize.from_lines(self.lines_changed)


@dataclass
class PRDetail:
    pr: PRData
    diff: str = ""
    files: list[str] = field(default_factory=list)
    review_comments: list[str] = field(default_factory=list)


@dataclass
class PRAnalysis:
    summary: str = ""
    security_risks: str = ""
    code_quality: str = ""
    risk_level: str = ""
    disruption_assessment: str = ""
    backwards_compatibility: str = ""
    semver_impact: str = ""
    review_comment: str = ""


@dataclass
class IssueData:
    number: int
    title: str
    author: str
    label: IssueLabel
    label_raw: str
    state: str
    created_at: datetime
    updated_at: datetime
    body: str = ""
    comment_count: int = 0


@dataclass
class IssueDetail:
    issue: IssueData
    comments: list[str] = field(default_factory=list)


@dataclass
class IssueAnalysis:
    severity: IssueSeverity = IssueSeverity.INFO
    overview: str = ""
    suspected_cause: str = ""
    suggested_fix: str = ""
