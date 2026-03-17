from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class GitHubIssue(BaseModel):
    """Represents a GitHub issue."""
    number: int
    title: str
    body: Optional[str] = None
    labels: List[str] = []
    created_at: str
    author: str
    url: str
    state: str = "open"


class IssueClassification(BaseModel):
    """Classification result for a GitHub issue."""
    severity: str  # critical, high, medium, low
    category: str  # bug, feature, docs, infra, security, performance, other
    recommended_action: str
    reasoning: Optional[str] = None


class ClassifiedIssue(BaseModel):
    """A GitHub issue with its classification."""
    issue: GitHubIssue
    classification: IssueClassification


class TriageReport(BaseModel):
    """Complete triage report for a repository."""
    repo: str
    total_issues: int
    generated_at: str
    issues: List[ClassifiedIssue]

    def to_sorted_json(self) -> str:
        """Return JSON sorted by priority (critical > high > medium > low)."""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(
            self.issues,
            key=lambda x: (
                severity_order.get(x.classification.severity, 4),
                x.issue.created_at
            )
        )
        # Create a new report with sorted issues
        sorted_report = TriageReport(
            repo=self.repo,
            total_issues=self.total_issues,
            generated_at=self.generated_at,
            issues=sorted_issues
        )
        return sorted_report.model_dump_json(indent=2)
