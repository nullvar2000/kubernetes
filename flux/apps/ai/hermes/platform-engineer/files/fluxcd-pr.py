#!/usr/bin/env python3
"""Open pull requests for pending fluxcd-*-image-update branches.

The ImageUpdateAutomations push tag bumps to fluxcd-<app>-image-update
branches; this job turns each pending branch (no open PR yet) into a PR
against main. Branches that already have an open PR are skipped — new
commits land on the existing PR automatically.

Mints a short-lived GitHub App installation token (1h expiry), same pattern
as gh-pr.py. No long-lived credentials are stored.

Env (from the agent-env configmap + agent-secrets):
    GH_APP_ID, GH_APP_INSTALLATION_ID, GH_PR_REPO, GH_APP_PRIVATE_KEY_B64
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
BRANCH_PREFIX = "fluxcd-"
BRANCH_SUFFIX = "-image-update"
BUMP_RE = re.compile(r"^(\S+) -> (\S+)$")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def get_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"fluxcd-pr: missing required env var {name}")
    return value


def mint_installation_token() -> str:
    app_id = get_env("GH_APP_ID")
    installation_id = get_env("GH_APP_INSTALLATION_ID")
    pem = base64.b64decode(get_env("GH_APP_PRIVATE_KEY_B64"))

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


def api_get(path: str, token: str):
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "fluxcd-image-update-prs",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def api_post(path: str, token: str, body: dict):
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "fluxcd-image-update-prs",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def build_title_and_body(app: str, branch: str, messages) -> tuple:
    """Title from the first old / last new tag; body lists every bump line."""
    bumps = [
        line.strip()
        for msg in messages
        for line in msg.splitlines()
        if BUMP_RE.match(line.strip())
    ]
    lines = [f"- `{bump}`" for bump in bumps] or [
        f"- {msg.splitlines()[0]}" for msg in messages
    ]
    if bumps:
        first_old = BUMP_RE.match(bumps[0]).group(1).rsplit(":", 1)[-1]
        last_new = BUMP_RE.match(bumps[-1]).group(2).rsplit(":", 1)[-1]
        title = f"chore({app}): image update {first_old} -> {last_new}"
    else:
        title = f"chore({app}): image update"
    body = (
        f"Automated image updates from the {app} ImageUpdateAutomation "
        f"(branch `{branch}`, {len(bumps)} bump(s)):\n\n" + "\n".join(lines)
    )
    return title, body


def main() -> None:
    repo = get_env("GH_PR_REPO")
    token = mint_installation_token()

    branches = sorted(
        b["name"]
        for b in api_get(f"/repos/{repo}/branches?per_page=100", token)
        if b["name"].startswith(BRANCH_PREFIX)
        and b["name"].endswith(BRANCH_SUFFIX)
    )
    open_heads = {
        pr["head"]["ref"]
        for pr in api_get(f"/repos/{repo}/pulls?state=open&per_page=100", token)
    }

    failures = 0
    for branch in branches:
        app = branch[len(BRANCH_PREFIX) : -len(BRANCH_SUFFIX)]
        if branch in open_heads:
            print(f"skip {branch}: open PR already exists")
            continue
        try:
            comparison = api_get(
                f"/repos/{repo}/compare/main...{urllib.parse.quote(branch, safe='')}",
                token,
            )
            if comparison.get("ahead_by", 0) == 0:
                print(f"skip {branch}: no commits ahead of main")
                continue
            messages = [c["commit"]["message"] for c in comparison.get("commits", [])]
            title, body = build_title_and_body(app, branch, messages)
            pr = api_post(
                f"/repos/{repo}/pulls",
                token,
                {"title": title, "head": branch, "base": "main", "body": body},
            )
            print(f"created PR for {branch}: {pr['html_url']}")
        except urllib.error.HTTPError as err:
            failures += 1
            detail = err.read().decode(errors="replace")
            print(f"error {branch}: HTTP {err.code}: {detail[:500]}")

    if failures:
        sys.exit(f"fluxcd-pr: {failures} branch(es) failed")
    print("fluxcd-pr: done")


if __name__ == "__main__":
    main()
