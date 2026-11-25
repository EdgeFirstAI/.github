#!/usr/bin/env python3
"""Check that every review comment on a pull request has been answered.

Passes when both hold:

- Copilot has submitted a review, or an organisation member or collaborator
  other than the author has approved.
- Every review thread started by Copilot or by a reviewer has a reply from a
  user other than the one who started it. Threads the author starts are exempt.

Thread resolution is not checked here; the ruleset's conversation-resolution
rule enforces it.

Environment: GH_TOKEN (pull-requests: read), GITHUB_REPOSITORY (owner/name),
PR_NUMBER, and optionally GITHUB_GRAPHQL_URL and GITHUB_STEP_SUMMARY.

Exit status: 0 pass, 1 fail, 2 bad environment or API error.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

COPILOT_LOGINS = frozenset({"copilot-pull-request-reviewer", "copilot-pull-request-reviewer[bot]"})
APPROVER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

REVIEWS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      author { login }
      reviews(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { state authorAssociation author { __typename login } }
      }
    }
  }
}
"""

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          path
          comments(first: 100) {
            nodes { url author { __typename login } }
          }
        }
      }
    }
  }
}
"""


def is_copilot(author: dict | None) -> bool:
    return bool(author) and author.get("login") in COPILOT_LOGINS


def is_user(author: dict | None) -> bool:
    return bool(author) and author.get("__typename") == "User" and not is_copilot(author)


def login(author: dict | None) -> str:
    return (author or {}).get("login", "")


def evaluate(pr_author: str, reviews: list[dict], threads: list[dict]) -> tuple[bool, list[str]]:
    """Return (passed, problems) for a pull request's reviews and review threads.

    `reviews` and `threads` are GraphQL `PullRequestReview` and
    `PullRequestReviewThread` nodes shaped as in the queries above.
    """
    problems: list[str] = []

    copilot_reviewed = any(is_copilot(r.get("author")) for r in reviews)
    approved = any(
        r.get("state") == "APPROVED"
        and r.get("authorAssociation") in APPROVER_ASSOCIATIONS
        and is_user(r.get("author"))
        and login(r.get("author")) != pr_author
        for r in reviews
    )
    if not (copilot_reviewed or approved):
        problems.append("Copilot has not reviewed this pull request yet, and no member or collaborator has approved it.")

    for thread in threads:
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        opener = comments[0].get("author")
        if is_user(opener) and login(opener) == pr_author:
            continue
        if any(is_user(c.get("author")) and login(c.get("author")) != login(opener) for c in comments[1:]):
            continue
        who = "Copilot" if is_copilot(opener) else login(opener) or "A reviewer"
        problems.append(f"{who}'s comment on {thread.get('path') or 'the pull request'} has no reply: {comments[0].get('url')}")

    return not problems, problems


def graphql(url: str, token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"]))
    return payload["data"]["repository"]["pullRequest"]


def fetch_all(url: str, token: str, query: str, field: str, variables: dict) -> tuple[dict, list[dict]]:
    """Page through `field` and return (first page's pull request object, all nodes)."""
    nodes: list[dict] = []
    first: dict | None = None
    after = None
    while True:
        pr = graphql(url, token, query, {**variables, "after": after})
        first = first or pr
        connection = pr[field]
        nodes.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return first, nodes
        after = connection["pageInfo"]["endCursor"]


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    number = os.environ.get("PR_NUMBER", "")
    url = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
    if not token or "/" not in repository or not number.isdigit():
        print("::error::GH_TOKEN, GITHUB_REPOSITORY and PR_NUMBER must be set")
        return 2

    owner, name = repository.split("/", 1)
    variables = {"owner": owner, "name": name, "number": int(number)}
    try:
        pr, reviews = fetch_all(url, token, REVIEWS_QUERY, "reviews", variables)
        _, threads = fetch_all(url, token, THREADS_QUERY, "reviewThreads", variables)
    except (urllib.error.URLError, RuntimeError, KeyError, TypeError) as exc:
        print(f"::error::GitHub API request failed: {exc}")
        return 2

    pr_author = (pr.get("author") or {}).get("login", "")
    passed, problems = evaluate(pr_author, reviews, threads)

    lines = ["## Review gate", ""]
    if passed:
        lines.append("Every review comment has been answered.")
        print("Every review comment has been answered.")
    else:
        for problem in problems:
            print(f"::error::{problem}")
            lines.append(f"- {problem}")
        lines += ["", "Reply to each comment saying how it was addressed or why it does not apply, then resolve it."]

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
