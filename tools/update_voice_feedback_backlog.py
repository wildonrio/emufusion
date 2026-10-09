#!/usr/bin/env python3
"""Build a reviewable bug/feature list from EmuFusion voice-feedback issues.

The generated document stores issue metadata and links only. Transcripts,
device diagnostics, and logs remain in their original GitHub issue instead of
being duplicated into the repository history.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request


TITLE_PREFIX = "[Device feedback]"
BUG_WORDS = re.compile(
    r"\b(bug|broken|breaks|crash|error|fail|freeze|flicker|hang|judder|lag|"
    r"missing|stutter|wrong|won't|cannot|can't|doesn't)\b",
    re.IGNORECASE,
)
FEATURE_WORDS = re.compile(
    r"\b(feature|request|add|allow|could|enhancement|improve|option|support|"
    r"would like|should have)\b",
    re.IGNORECASE,
)


def fetch_issues(repository: str, token: str = "") -> list[dict]:
    issues: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"state": "open", "per_page": 100, "page": page})
        url = f"https://api.github.com/repos/{repository}/issues?{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "EmuFusion-Voice-Feedback-Backlog/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub issues response was not a list")
        issues.extend(item for item in batch if "pull_request" not in item)
        if len(batch) < 100:
            break
        page += 1
    return issues


def category(issue: dict) -> str:
    labels = {
        str(item.get("name", "")).strip().lower()
        for item in issue.get("labels", [])
        if isinstance(item, dict)
    }
    if labels & {"bug", "type: bug"}:
        return "Bugs"
    if labels & {"enhancement", "feature", "type: feature"}:
        return "Feature requests"
    title = str(issue.get("title", ""))[len(TITLE_PREFIX):].strip()
    if BUG_WORDS.search(title):
        return "Bugs"
    if FEATURE_WORDS.search(title):
        return "Feature requests"
    return "Needs review"


def render(repository: str, issues: list[dict]) -> str:
    groups = {"Bugs": [], "Feature requests": [], "Needs review": []}
    for issue in issues:
        title = str(issue.get("title", ""))
        if not title.startswith(TITLE_PREFIX):
            continue
        groups[category(issue)].append(issue)

    lines = [
        "# EmuFusion voice-feedback backlog",
        "",
        "This list is generated from open GitHub issues created through the "
        "EmuFusion voice-feedback flow. Transcriptions, diagnostics, and logs "
        "remain in the linked issue and are not duplicated here.",
        "",
        f"Repository: [{repository}](https://github.com/{repository}/issues)",
        "",
    ]
    for heading in ("Bugs", "Feature requests", "Needs review"):
        items = sorted(groups[heading], key=lambda item: int(item.get("number", 0)))
        lines.extend((f"## {heading}", ""))
        if not items:
            lines.extend(("- None.", ""))
            continue
        for item in items:
            number = int(item.get("number", 0))
            title = str(item.get("title", ""))[len(TITLE_PREFIX):].strip()
            url = str(item.get("html_url", f"https://github.com/{repository}/issues/{number}"))
            updated = str(item.get("updated_at", ""))[:10] or "unknown"
            lines.append(f"- [#{number} — {title}]({url}) · updated {updated}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="wildonrio/emufusion")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("docs/VOICE-FEEDBACK-BACKLOG.md"),
    )
    parser.add_argument("--input", type=pathlib.Path,
                        help="Optional JSON fixture instead of GitHub")
    args = parser.parse_args()
    if args.input:
        issues = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        issues = fetch_issues(args.repo, os.environ.get("GITHUB_TOKEN", ""))
    output = render(args.repo, issues)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_text(encoding="utf-8") != output:
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
