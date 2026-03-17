"""LLM-based issue classifier for triage."""
import json
import os
from typing import List

import httpx
from openai import OpenAI
from pydantic import ValidationError

from models import GitHubIssue, IssueClassification, ClassifiedIssue
from prompts import SYSTEM_PROMPT


def get_llm_client():
    """Initialize LLM client (supports Z.ai/GLM, MiniMax, OpenAI)."""
    # Try Z.ai/GLM first
    api_key = os.environ.get("ZAI_API_KEY") or os.environ.get("GLM_API_KEY")
    if api_key:
        base_url = "https://api.z.ai/api/coding/paas/v4"
        client = OpenAI(api_key=api_key, base_url=base_url)
        return "glm", api_key, client

    # Try OpenAI
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return "openai", api_key, OpenAI(api_key=api_key)

    # Try MiniMax (using Anthropic-compatible endpoint)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    if api_key and "minimax" in base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
        return "minimax", api_key, client

    raise ValueError("No LLM API key set (ZAI_API_KEY, GLM_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY)")


def build_classification_prompt(issues: List[GitHubIssue]) -> str:
    """Build the user message with issues to classify."""
    issues_data = []
    for issue in issues:
        issues_data.append({
            "number": issue.number,
            "title": issue.title,
            "body": issue.body[:500] if issue.body else "",  # Truncate long bodies
            "labels": issue.labels,
            "author": issue.author,
            "created_at": issue.created_at
        })

    return f"""Classify the following {len(issues)} GitHub issues by severity and category.

Issues:
{json.dumps(issues_data, indent=2)}

For each issue, provide:
- number: The issue number (must match input)
- severity: critical, high, medium, or low
- category: bug, feature, docs, infra, security, performance, or other
- recommended_action: Clear action to take
- reasoning: Brief explanation

Return a JSON array of classification objects."""


def parse_classification_response(content: str, expected_count: int) -> List[dict]:
    """Parse the LLM response and extract classifications."""
    # Clean up the response
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # Parse JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\nContent: {content}")

    # Ensure it's a list
    if isinstance(data, dict):
        # Handle single object or wrapped response
        if "classifications" in data:
            data = data["classifications"]
        else:
            data = [data]

    return data


async def classify_issues_async(issues: List[GitHubIssue]) -> List[ClassifiedIssue]:
    """
    Classify a list of GitHub issues using LLM (async version).

    Args:
        issues: List of GitHubIssue objects to classify

    Returns:
        List of ClassifiedIssue objects with classifications
    """
    if not issues:
        return []

    client_type, api_key, openai_client = get_llm_client()
    user_message = build_classification_prompt(issues)
    content = None

    if client_type in ("glm", "openai"):
        # Use OpenAI-compatible API
        model = "glm-4.5" if client_type == "glm" else "gpt-4o-mini"
        response = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
    elif client_type == "minimax":
        # Use MiniMax API (sync httpx client)
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
        model = os.environ.get("ANTHROPIC_MODEL", "MiniMax-Text-01")
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model,
            "max_tokens": 4000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
            "extra_body": {"json": True}
        }
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{base_url}/v1/messages",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            content_array = data["content"]
            for item in content_array:
                if item.get("type") == "text":
                    content = item["text"]
                    break
            else:
                content = content_array[0].get("text", str(content_array))
    else:
        raise ValueError(f"Unsupported client type: {client_type}")

    # Parse classifications
    raw_classifications = parse_classification_response(content, len(issues))

    # Map issue numbers to issues for quick lookup
    issue_by_number = {issue.number: issue for issue in issues}

    classified_issues = []
    for classification_data in raw_classifications:
        issue_number = classification_data.get("number")
        if issue_number is None:
            continue

        issue = issue_by_number.get(issue_number)
        if issue is None:
            continue

        try:
            classification = IssueClassification(
                severity=classification_data.get("severity", "medium"),
                category=classification_data.get("category", "other"),
                recommended_action=classification_data.get("recommended_action", "Review and triage"),
                reasoning=classification_data.get("reasoning")
            )
            classified_issues.append(ClassifiedIssue(
                issue=issue,
                classification=classification
            ))
        except ValidationError as e:
            # Skip invalid classifications
            continue

    # If some issues weren't classified, add them with default classification
    classified_numbers = {c.issue.number for c in classified_issues}
    for issue in issues:
        if issue.number not in classified_numbers:
            classified_issues.append(ClassifiedIssue(
                issue=issue,
                classification=IssueClassification(
                    severity="medium",
                    category="other",
                    recommended_action="Manual review needed",
                    reasoning="LLM classification failed"
                )
            ))

    return classified_issues


def classify_issues(issues: List[GitHubIssue]) -> List[ClassifiedIssue]:
    """Synchronous wrapper for classify_issues_async."""
    import asyncio
    return asyncio.run(classify_issues_async(issues))
