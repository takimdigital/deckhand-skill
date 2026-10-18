"""The owner's GitHub, used as their personal library: private base repos + one index repo.

Stdlib only. The token comes from the vault (`dh vault set GITHUB_TOKEN`, a fine-grained token with
"Administration: write" to create repos and "Contents: write" to push) and is handed to git through the
environment (GIT_CONFIG_* variables) — never on a command line, never in a remote URL, never on disk.
DH_GITHUB_API / DH_GITHUB_GIT point elsewhere for tests (a local mock API and file:// remotes).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from .util import DhError, run
from . import profile as PROFILE

API = lambda: os.environ.get("DH_GITHUB_API", "https://api.github.com").rstrip("/")  # noqa: E731
GIT = lambda: os.environ.get("DH_GITHUB_GIT", "https://github.com").rstrip("/")     # noqa: E731


def token(required: bool = True) -> str | None:
    t = PROFILE.secret("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not t and required:
        raise DhError("NO_GITHUB_TOKEN", "ACTION NEEDED — create a fine-grained GitHub token (github.com → Settings → Developer settings → "
                      "Fine-grained tokens → Repository access: All repositories · Permissions: Administration + Contents = Read and write), "
                      "then `dh vault set GITHUB_TOKEN` (paste it; it is stored 0600, never printed)")
    return t


def api(method: str, path: str, body: dict | None = None, ok=(200, 201, 204)):
    req = urllib.request.Request(API() + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "deckhand/2",
                                          "Authorization": f"Bearer {token()}", **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8") or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            data = {}
        if e.code in ok:
            return e.code, data
        return e.code, data


def me() -> str:
    st, d = api("GET", "/user")
    if st != 200:
        raise DhError("GITHUB_AUTH", f"GitHub rejected the token (HTTP {st}): {d.get('message', '')}")
    return d["login"]


def ensure_repo(full: str, description: str = "", private: bool = True) -> dict:
    """Create owner/name if missing (private by default). Returns {created, empty}."""
    owner, name = full.split("/", 1)
    st, d = api("GET", f"/repos/{full}")
    if st == 200:
        return {"created": False, "private": d.get("private"), "empty": d.get("size", 0) == 0}
    login = me()
    path = "/user/repos" if owner.lower() == login.lower() else f"/orgs/{owner}/repos"
    st, d = api("POST", path, {"name": name, "private": private, "description": description[:300], "auto_init": False})
    if st not in (200, 201):
        raise DhError("GITHUB_CREATE", f"could not create {full} (HTTP {st}): {d.get('message', '')} — the token needs Administration: write")
    return {"created": True, "private": d.get("private", private), "empty": True}


def git_env() -> dict:
    """Auth for git over HTTPS, passed as environment config (not visible in `ps`, not stored)."""
    basic = base64.b64encode(f"x-access-token:{token()}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{GIT()}/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            "GIT_TERMINAL_PROMPT": "0"}


def remote(full: str) -> str:
    return f"{GIT()}/{full}.git"


def push(dest, full: str, branch: str = "main") -> dict:
    run(["git", "branch", "-M", branch], cwd=dest)
    r = run(["git", "push", remote(full), f"HEAD:refs/heads/{branch}"], cwd=dest, timeout=600, env=git_env())
    if r["code"] != 0:
        raise DhError("GITHUB_PUSH", (r["err"] or r["out"])[-400:].replace(token(False) or "\0", "***"))
    return {"pushed": full, "branch": branch}


def clone(full: str, to, branch: str | None = None) -> dict:
    args = ["git", "clone", "--depth", "1"] + (["--branch", branch] if branch else []) + [remote(full), str(to)]
    r = run(args, timeout=900, env=git_env() if token(False) else None)
    if r["code"] != 0:
        raise DhError("CLONE_FAILED", (r["err"] or r["out"])[-400:])
    return {"cloned": full}


def get_file(full: str, path: str):
    st, d = api("GET", f"/repos/{full}/contents/{path}", ok=(200, 404))
    if st == 404:
        return None, None
    if st != 200:
        raise DhError("GITHUB_READ", f"{full}/{path}: HTTP {st} {d.get('message', '')}")
    return base64.b64decode(d.get("content", "")).decode("utf-8"), d.get("sha")


def put_file(full: str, path: str, text: str, message: str, sha: str | None = None) -> None:
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    st, d = api("PUT", f"/repos/{full}/contents/{path}", body)
    if st not in (200, 201):
        raise DhError("GITHUB_WRITE", f"{full}/{path}: HTTP {st} {d.get('message', '')}")
