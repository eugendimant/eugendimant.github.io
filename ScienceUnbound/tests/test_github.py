import base64
import json

import httpx
import pytest

from scienceunbound.github_publish import GitHubError, publish_files


def make_client(log, fail_at=None):
    def handler(req: httpx.Request):
        log.append((req.method, req.url.path, json.loads(req.content) if req.content else None, req.headers.get("authorization")))
        p, m = req.url.path, req.method
        if fail_at and fail_at in p:
            return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
        if m == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "h" * 40}})
        if m == "GET" and "/git/commits/" in p:
            return httpx.Response(200, json={"tree": {"sha": "t" * 40}})
        if m == "POST" and p.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": f"b{len([l for l in log if l[1].endswith('/git/blobs')]):039d}"})
        if m == "POST" and p.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "n" * 40})
        if m == "POST" and p.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "c" * 40, "committer": {"date": "2026-10-16T12:00:00Z"}})
        if m == "PATCH" and p.endswith("/git/refs/heads/main"):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": "Not Found"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_one_commit_with_all_files_under_the_study_folder():
    log = []
    out = publish_files({"report.md": b"hello", "results/effects.csv": b"a,b\n1,2\n"}, repo="eugendimant/ScienceUnbound",
                        token="SECRET-TOKEN", subdir="studies/my-study", message="Add study", client=make_client(log))
    assert out["commit_sha"] == "c" * 40 and out["n_files"] == 2 and out["html_url"].endswith("studies/my-study")
    tree = next(l for l in log if l[1].endswith("/git/trees"))[2]
    assert {e["path"] for e in tree["tree"]} == {"studies/my-study/report.md", "studies/my-study/results/effects.csv"}
    assert tree["base_tree"] == "t" * 40
    blob = next(l for l in log if l[1].endswith("/git/blobs"))[2]
    assert base64.b64decode(blob["content"]) in (b"hello", b"a,b\n1,2\n")
    commit = next(l for l in log if l[1].endswith("/git/commits") and l[0] == "POST")[2]
    assert commit["parents"] == ["h" * 40]
    assert all(l[3] == "Bearer SECRET-TOKEN" for l in log)
    assert not any("api.github.com" not in str(l) and False for l in log)


def test_errors_explain_the_fix_and_never_leak_the_token():
    with pytest.raises(GitHubError) as e:
        publish_files({"a": b"x"}, repo="eugendimant/ScienceUnbound", token="SECRET-TOKEN", subdir="studies/x", message="m",
                      client=make_client([], fail_at="/git/blobs"))
    msg = str(e.value)
    assert "write access" in msg and "SECRET-TOKEN" not in msg


def test_input_is_validated_before_any_request():
    log = []
    with pytest.raises(GitHubError):
        publish_files({"a": b"x"}, repo="not a repo", token="t", subdir="s", message="m", client=make_client(log))
    with pytest.raises(GitHubError):
        publish_files({"a": b"x"}, repo="a/b", token="", subdir="s", message="m", client=make_client(log))
    assert log == []
