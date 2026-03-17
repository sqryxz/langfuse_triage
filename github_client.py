"""GitHub API client for fetching repository issues."""
import os
from typing import List, Optional
from github import Github
from models import GitHubIssue


class GitHubClient:
    """Client for interacting with GitHub API to fetch issues."""

    DEFAULT_REPO = "postfiat/langfuse"

    def __init__(self, token: Optional[str] = None):
        """Initialize GitHub client with optional token."""
        self.token = token or os.getenv("GITHUB_TOKEN")
        if self.token:
            self.client = Github(self.token)
        else:
            self.client = Github()

    def get_open_issues(
        self,
        repo: Optional[str] = None,
        max_issues: int = 100
    ) -> List[GitHubIssue]:
        """
        Fetch open issues from a GitHub repository.

        Args:
            repo: Repository in owner/repo format (default: postfiat/langfuse)
            max_issues: Maximum number of issues to fetch

        Returns:
            List of GitHubIssue objects
        """
        repo = repo or self.DEFAULT_REPO

        try:
            github_repo = self.client.get_repo(repo)
        except Exception as e:
            raise ValueError(f"Failed to access repository {repo}: {e}")

        issues = []
        # Get open issues with pagination
        for issue in github_repo.get_issues(state="open"):
            # Skip pull requests (they're also issues in GitHub API)
            if issue.pull_request:
                continue

            # Extract labels
            labels = [label.name for label in issue.labels] if issue.labels else []

            # Get author login
            author = issue.user.login if issue.user else "unknown"

            # Format created_at
            created_at = issue.created_at.isoformat() if issue.created_at else ""

            issues.append(GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body,
                labels=labels,
                created_at=created_at,
                author=author,
                url=issue.html_url,
                state=issue.state
            ))

            if len(issues) >= max_issues:
                break

        return issues
