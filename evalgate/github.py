"""GitHub integration: step summary + pull-request comment.

Every failure mode degrades gracefully: outside GitHub (a laptop, a
plain CI runner, a test) these functions are silent no-ops. The gate
itself never fails because a comment could not be posted.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def write_step_summary(markdown: str) -> bool:
    """Append the report to $GITHUB_STEP_SUMMARY when available."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
        return True
    except OSError as exc:
        print(f"evalgate: could not write step summary: {exc}", file=sys.stderr)
        return False


def _pr_number() -> int | None:
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/pull/") and ref.endswith("/merge"):
        try:
            return int(ref.split("/")[2])
        except (IndexError, ValueError):
            return None
    return None


def post_pr_comment(markdown: str) -> bool:
    """Post (or update) the report as a PR comment when running in a PR.

    Uses the workflow-provided GITHUB_TOKEN; requires the action to be
    granted `pull-requests: write`. Missing token or context -> no-op.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    pr = _pr_number()
    if not (token and repo and pr):
        return False

    marker = "<!-- evalgate-report -->"
    body = f"{marker}\n{markdown}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "svx-evalgate",
    }

    try:
        # Update an existing EvalGate comment when present, else create.
        list_url = f"{api}/repos/{repo}/issues/{pr}/comments?per_page=100"
        req = urllib.request.Request(list_url, headers={
            k: v for k, v in headers.items() if k != "Content-Type"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
        for comment in comments:
            if marker in (comment.get("body") or ""):
                edit_url = f"{api}/repos/{repo}/issues/comments/{comment['id']}"
                data = json.dumps({"body": body}).encode("utf-8")
                req = urllib.request.Request(edit_url, data=data, headers=headers,
                                             method="PATCH")
                urllib.request.urlopen(req, timeout=30).close()
                return True

        create_url = f"{api}/repos/{repo}/issues/{pr}/comments"
        data = json.dumps({"body": body}).encode("utf-8")
        req = urllib.request.Request(create_url, data=data, headers=headers,
                                     method="POST")
        urllib.request.urlopen(req, timeout=30).close()
        return True
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        print(f"evalgate: could not post PR comment: {exc}", file=sys.stderr)
        return False
