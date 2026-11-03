#!/usr/bin/env python3
"""Security-review plumbing for the infosec-engineer agent.

Mints a short-lived GitHub App installation token (same chain as gh-pr.py),
lists in-scope PRs whose head_sha has not been reviewed yet, fetches diffs,
and submits reviews. Deterministic plumbing; the review itself is the agent.

Usage:
    gh-review.py pending                      JSON array of PRs to review
    gh-review.py diff <pr>                    unified diff (stdout, max 200KB)
    gh-review.py submit <pr> <event> <body>   post review; event =
                                              APPROVE|REQUEST_CHANGES|COMMENT
                                              (<body> is a file path)
    gh-review.py comment <pr> <body-file>     post a plain PR comment

Scope (any one qualifies):
    - changed file matches SECURITY_PATHS
    - head branch starts with 'platform-engineer/' or 'fluxcd-'
    - PR carries the label 'security-review'
PRs pushed by this agent (head starts 'infosec-engineer/') are skipped.

Env: GH_APP_ID, GH_APP_INSTALLATION_ID, GH_APP_PRIVATE_KEY_B64, GH_PR_REPO,
     GH_WORKDIR (default /opt/data/k8s-repo),
     GH_SECURITY_STATE (default /opt/data/.work/gh-review-state.json)
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

API = "https://api.github.com"
SECURITY_PATHS = [re.compile(p) for p in (
    r"^flux/infrastructure/kyverno",
    r"^flux/infrastructure/.*stackrox",
    r"rbac\.ya?ml$",
    r"networkpolicy",
    r"httproute",
    r"ingress",
    r"\.clear\.yaml$",
    r"(^|/)secrets",
    r"\.sops\.ya?ml$",
)]
BOT_BRANCHES = ("platform-engineer/", "fluxcd-")
SELF_BRANCH = "infosec-engineer/"
DIFF_LIMIT = 200_000


def env(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"gh-review: missing required env var {name}")
    return value


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_installation_token() -> str:
    app_id = env("GH_APP_ID")
    installation_id = env("GH_APP_INSTALLATION_ID")
    pem = base64.b64decode(env("GH_APP_PRIVATE_KEY_B64"))
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
        sig = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", keyfile],
            input=f"{header}.{payload}".encode(),
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


def api(path, token, method="GET", payload=None, accept=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept or "application/vnd.github+json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{API}{path}", data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
    if accept and "diff" in accept:
        return raw.decode(errors="replace")
    return json.loads(raw)


def repo():
    return env("GH_PR_REPO")


def state_path():
    return env("GH_SECURITY_STATE", "/opt/data/.work/gh-review-state.json")


def state_load():
    try:
        return json.load(open(state_path()))
    except (OSError, ValueError):
        return {}


def state_save(state):
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=1)


def ensure_repo(token):
    workdir = env("GH_WORKDIR", "/opt/data/k8s-repo")
    if not os.path.isdir(os.path.join(workdir, ".git")):
        url = f"https://x-access-token:{token}@github.com/{repo()}.git"
        subprocess.run(
            ["git", "clone", url, workdir], capture_output=True, text=True, check=True
        )


def open_prs(token):
    return api(f"/repos/{repo()}/pulls?state=open&per_page=100", token)


def pr_detail(token, number):
    return api(f"/repos/{repo()}/pulls/{number}", token)


def changed_files(token, number):
    page = api(
        f"/repos/{repo()}/pulls/{number}/files?per_page=100", token
    )
    return [f["filename"] for f in page]


def in_scope(token, pr):
    if pr["head"]["ref"].startswith(BOT_BRANCHES):
        return "bot-branch"
    labels = [l["name"] for l in pr.get("labels", [])]
    if "security-review" in labels:
        return "label"
    for path in changed_files(token, pr["number"]):
        for rx in SECURITY_PATHS:
            if rx.search(path):
                return f"path:{path}"
    return None


def cmd_pending(token):
    state = state_load()
    ensure_repo(token)
    out = []
    for pr in open_prs(token):
        if pr["head"]["ref"].startswith(SELF_BRANCH):
            continue
        sha = pr["head"]["sha"]
        if state.get(str(pr["number"])) == sha:
            continue
        reason = in_scope(token, pr)
        if reason:
            out.append({
                "number": pr["number"],
                "title": pr["title"],
                "head_sha": sha,
                "head_ref": pr["head"]["ref"],
                "scope": reason,
            })
    print(json.dumps(out, indent=1))


def cmd_diff(token, number):
    diff = api(
        f"/repos/{repo()}/pulls/{number}",
        token,
        accept="application/vnd.github.diff",
    )
    sys.stdout.write(diff[:DIFF_LIMIT])
    if len(diff) > DIFF_LIMIT:
        sys.stdout.write("\n... diff truncated ...")


def cmd_submit(token, number, event, body_file):
    if event not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        sys.exit(f"gh-review: invalid event {event!r}")
    body = open(body_file).read()
    pr = pr_detail(token, number)
    api(
        f"/repos/{repo()}/pulls/{number}/reviews",
        token,
        method="POST",
        payload={"event": event, "body": body, "commit_sha": pr["head"]["sha"]},
    )
    state = state_load()
    state[str(number)] = pr["head"]["sha"]
    state_save(state)
    print(f"review {event} posted on PR #{number} at {pr['head']['sha']}")


def cmd_comment(token, number, body_file):
    body = open(body_file).read()
    api(
        f"/repos/{repo()}/issues/{number}/comments",
        token,
        method="POST",
        payload={"body": body},
    )
    print(f"comment posted on PR #{number}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    token = mint_installation_token()
    if cmd == "pending":
        cmd_pending(token)
    elif cmd == "diff" and len(args) == 1:
        cmd_diff(token, int(args[0]))
    elif cmd == "submit" and len(args) == 3:
        cmd_submit(token, int(args[0]), args[1], args[2])
    elif cmd == "comment" and len(args) == 2:
        cmd_comment(token, int(args[0]), args[1])
    else:
        sys.exit(f"gh-review: bad invocation: {sys.argv[1:]}")


if __name__ == "__main__":
    main()
