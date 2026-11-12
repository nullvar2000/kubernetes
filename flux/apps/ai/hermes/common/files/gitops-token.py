#!/usr/bin/env python3
"""Mint a short-lived GitHub App installation token and print it to stdout.

Shared by seed.sh (first-boot clone) and git-fetch-origin.sh (later fetches).
gh-pr.py keeps its own copy of this logic — it must stay standalone because
it is mounted as a single script into the agent container.

Env (from agent-env ConfigMap + agent-secrets Secret):
    GH_APP_ID, GH_APP_INSTALLATION_ID, GH_APP_PRIVATE_KEY_B64
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


def main() -> None:
    app_id = os.environ["GH_APP_ID"]
    installation_id = os.environ["GH_APP_INSTALLATION_ID"]
    pem = base64.b64decode(os.environ["GH_APP_PRIVATE_KEY_B64"])

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
        print(json.load(resp)["token"])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # nosec - only error type reported, no secret data
        print(f"gitops-token: {e}", file=sys.stderr)
        sys.exit(1)
