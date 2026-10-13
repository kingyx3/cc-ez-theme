#!/usr/bin/env python3
"""Open one actionable GitHub issue per failed production monitor; close on recovery.

Uses Actions' short-lived GITHUB_TOKEN (Issues: write). Never handles EasyStore
credentials or logs GitHub API response bodies.
"""
import json
import os
import subprocess
import sys

COMPONENTS = {
    "admin-renewal": "production admin token renewal",
    "mcp-health": "production MCP health check",
    "mcp-deploy": "production MCP deployment",
}


def gh(*arguments):
    result = subprocess.run(["gh", *arguments], text=True, capture_output=True, check=True, timeout=30)
    return result.stdout


def reconcile(component, status, repo, owner, run_url):
    if component not in COMPONENTS or status not in {"success", "failure"}:
        raise ValueError("Unsupported EasyStore alert component or job status.")
    title = f"[EasyStore] {COMPONENTS[component]} failed"
    issues = json.loads(gh("issue", "list", "--repo", repo, "--state", "open",
                          "--limit", "500", "--json", "number,title"))
    issue = next((entry for entry in issues if entry.get("title") == title), None)
    if status == "failure":
        body = ("The production monitor failed. Check the run and investigate the credential, "
                "store routing, or hosted MCP response. Do not post credentials in this issue.\n\n"
                f"Failed run: {run_url}\n")
        if issue:
            gh("issue", "comment", str(issue["number"]), "--repo", repo, "--body", body)
        else:
            gh("issue", "create", "--repo", repo, "--title", title,
               "--body", body, "--assignee", owner)
        print(f"GitHub incident recorded: {title}")
    elif issue:
        gh("issue", "comment", str(issue["number"]), "--repo", repo,
           "--body", f"Recovered: {run_url}")
        gh("issue", "close", str(issue["number"]), "--repo", repo)
        print(f"Resolved GitHub incident: {title}")
    else:
        print(f"No open incident: {title}")


def main():
    env = os.environ
    repo = env.get("GITHUB_REPOSITORY", "")
    owner = env.get("GITHUB_REPOSITORY_OWNER", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    component = env.get("EASYSTORE_ALERT_COMPONENT", "")
    status = env.get("EASYSTORE_ALERT_STATUS", "")
    if not (repo and owner and run_id and env.get("GH_TOKEN")):
        print("::error::Missing GitHub issue alert configuration.", file=sys.stderr)
        return 1
    url = f"https://github.com/{repo}/actions/runs/{run_id}"
    try:
        reconcile(component, status, repo, owner, url)
        return 0
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print("::error::Could not create/update the EasyStore incident issue. Verify Issues are enabled and Actions has issues:write.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
