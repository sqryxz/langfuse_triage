"""Langfuse Issue Triage MCP Server."""
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
import uvicorn
from mcp.server import Server
from mcp.types import Tool, TextContent
from pydantic import BaseModel

from models import GitHubIssue, ClassifiedIssue, TriageReport
from github_client import GitHubClient
from classifier import classify_issues


# Initialize MCP server
mcp_server = Server("langfuse-triage")


class TriageRequest(BaseModel):
    """Request model for triage endpoint."""
    repo: str = "postfiat/langfuse"
    max_issues: int = 50


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="triage_issues",
            description="Fetch and classify open GitHub issues from a repository, returning a prioritized triage report with severity, category, and recommended actions",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "GitHub repository in owner/repo format (default: postfiat/langfuse)",
                        "default": "postfiat/langfuse"
                    },
                    "max_issues": {
                        "type": "number",
                        "description": "Maximum number of issues to fetch (default: 50)",
                        "default": 50
                    }
                }
            }
        )
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    if name == "triage_issues":
        return await triage_issues(
            repo=arguments.get("repo", "postfiat/langfuse"),
            max_issues=arguments.get("max_issues", 50)
        )
    else:
        raise ValueError(f"Unknown tool: {name}")


async def triage_issues(
    repo: str = "postfiat/langfuse",
    max_issues: int = 50
) -> list[TextContent]:
    """Fetch and classify GitHub issues."""
    try:
        # Initialize clients
        github_client = GitHubClient()

        # Fetch open issues
        issues = github_client.get_open_issues(repo=repo, max_issues=max_issues)

        if not issues:
            return [TextContent(type="text", text='{"repo": "postfiat/langfuse", "total_issues": 0, "issues": [], "message": "No open issues found"}')]

        # Classify issues using LLM
        classified_issues = classify_issues(issues)

        # Build triage report
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(
            classified_issues,
            key=lambda x: (
                severity_order.get(x.classification.severity, 4),
                x.issue.created_at
            )
        )

        report = TriageReport(
            repo=repo,
            total_issues=len(issues),
            generated_at=datetime.utcnow().isoformat() + "Z",
            issues=sorted_issues
        )

        return [TextContent(type="text", text=report.to_sorted_json())]

    except Exception as e:
        return [TextContent(type="text", text=f'{{"error": "{str(e)}"}}')]


async def main():
    """Run the MCP server."""
    async with mcp_server.run() as runner:
        await runner.listen_stdio()


# FastAPI app for optional HTTP server
app = FastAPI(title="Langfuse Issue Triage MCP Server")


@app.post("/triage")
async def triage_endpoint(request: TriageRequest) -> dict:
    """HTTP endpoint for triaging issues."""
    github_client = GitHubClient()
    issues = github_client.get_open_issues(repo=request.repo, max_issues=request.max_issues)

    if not issues:
        return {
            "repo": request.repo,
            "total_issues": 0,
            "issues": [],
            "message": "No open issues found"
        }

    classified_issues = classify_issues(issues)

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_issues = sorted(
        classified_issues,
        key=lambda x: (
            severity_order.get(x.classification.severity, 4),
            x.issue.created_at
        )
    )

    report = TriageReport(
        repo=request.repo,
        total_issues=len(issues),
        generated_at=datetime.utcnow().isoformat() + "Z",
        issues=sorted_issues
    )

    return json.loads(report.to_sorted_json())


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


import json

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        # Run as HTTP server
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Run as stdio MCP server
        import asyncio
        asyncio.run(main())
