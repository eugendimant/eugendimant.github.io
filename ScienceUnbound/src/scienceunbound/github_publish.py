"""Commit a study package to a GitHub repository in ONE commit through the Git Data API.

The token is read by the caller (Streamlit secret or environment) and sent only to api.github.com in an Authorization
header. It is never logged, written to disk or included in an error message.
"""
from __future__ import annotations

import base64
import re

import httpx

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubError(RuntimeError):
    pass


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = ""
        hint = {401: "the token is invalid or expired", 403: "the token lacks write access to this repository",
                404: "the repository or branch was not found (private repositories also answer 404 without access)",
                409: "the repository is empty: create a first commit (for example a README) and try again",
                422: "GitHub rejected the request"}.get(r.status_code, "")
        raise GitHubError(f"{what} failed: HTTP {r.status_code} {msg} {hint}".strip())
    return r.json()


def publish_files(files: dict[str, bytes], *, repo: str, token: str, subdir: str, message: str, branch: str = "main",
                  client: httpx.Client | None = None, api: str = API, remove_prefix: bool = False) -> dict:
    if not REPO_RE.match(repo):
        raise GitHubError("repository must look like owner/name")
    if not token:
        raise GitHubError("no GitHub token configured")
    own = client is None
    c = client or httpx.Client(timeout=30)
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        ref = _check(c.get(f"{api}/repos/{repo}/git/ref/heads/{branch}", headers=h), "reading the branch")
        head = ref["object"]["sha"]
        commit = _check(c.get(f"{api}/repos/{repo}/git/commits/{head}", headers=h), "reading the head commit")
        entries = []
        for rel, blob in sorted(files.items()):
            b = _check(c.post(f"{api}/repos/{repo}/git/blobs", headers=h,
                              json={"content": base64.b64encode(blob).decode(), "encoding": "base64"}), f"uploading {rel}")
            entries.append({"path": f"{subdir.strip('/')}/{rel}", "mode": "100644", "type": "blob", "sha": b["sha"]})
        tree = _check(c.post(f"{api}/repos/{repo}/git/trees", headers=h,
                             json={"base_tree": commit["tree"]["sha"], "tree": entries}), "creating the tree")
        new = _check(c.post(f"{api}/repos/{repo}/git/commits", headers=h,
                            json={"message": message, "tree": tree["sha"], "parents": [head]}), "creating the commit")
        _check(c.patch(f"{api}/repos/{repo}/git/refs/heads/{branch}", headers=h, json={"sha": new["sha"]}), "updating the branch")
        return {"commit_sha": new["sha"], "commit_url": f"https://github.com/{repo}/commit/{new['sha']}",
                "html_url": f"https://github.com/{repo}/tree/{branch}/{subdir.strip('/')}", "n_files": len(entries),
                "committed_at": new.get("committer", {}).get("date", "")}
    finally:
        if own:
            c.close()
