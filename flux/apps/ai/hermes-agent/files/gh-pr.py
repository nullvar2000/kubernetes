#!/usr/bin/env python3
"""Publish the current git branch of the GitOps repo as a pull request.

Mints a short-lived GitHub App installation token (1h expiry), pushes the
branch, and opens a PR against main. No long-lived credentials are stored.

Usage:
    python3 gh-pr.py <branch> <pr-title> [body-file]

Env (from the hermes-agent agent-env configmap):
    GH_APP_ID, GH_APP_INSTALLATION_ID, GH_APP_PRIVATE_KEY_B64, GH_PR_REPO
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

API = "https://api.github.com"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def get_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"gh-pr: missing required env var {name}")
    return value


def mint_installation_token() -> str:
    app_id = get_env("GH_APP_ID")
    installation_id = get_env("GH_APP_INSTALLATION_ID")
    key_b64 = get_env("GH_APP_PRIVATE_KEY_B64")
    pem = base64.b64decode(key_b64)

    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(
        json.dumps({"iss": int(app_id), "iat": now - 60, "exp": now + 300}).encode()
    )
    fd, keyfile = tempfile.mkstemp(prefix="gh-app-key-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        signing_input = f"{header}.{payload}".encode()
        sig = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", keyfile],
            input=signing_input,
            capture_output=True,
            check=True,
        ).stdout
    finally:
        os.unlink(keyfile)
    jwt = f"{header}.{payload}.{b64url(sig)}"

    req = urllib.request.Request(
        f"{API}/app/installations/{installation_id}/access_tokens",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["token"]


def push_branch(token: str, branch: str) -> None:
    repo = get_env("GH_PR_REPO")
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    result = subprocess.run(
        ["git", "push", url, f"HEAD:refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(
            f"gh-pr: git push failed:\n{result.stdout}\n{result.stderr}"
        )


def open_pr(token: str, branch: str, title: str, body: str) -> str:
    repo = get_env("GH_PR_REPO")
    payload = json.dumps(
        {"title": title, "head": branch, "base": "main", "body": body}
    ).encode()
    req = urllib.request.Request(
        f"{API}/repos/{repo}/pulls",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["html_url"]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: gh-pr.py <branch> <pr-title> [body-file]")
    branch, title = sys.argv[1], sys.argv[2]
    body = (
        open(sys.argv[3]).read()
        if len(sys.argv) > 3
        else f"Created by the platform-engineer agent via GitHub App."
    )
    token = mint_installation_token()
    push_branch(token, branch)
    pr_url = open_pr(token, branch, title, body)
    print(pr_url)


if __name__ == "__main__":
    main()
