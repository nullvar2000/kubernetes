#!/usr/bin/env python3
"""Alertmanager -> Mattermost relay.

Receives Alertmanager webhook notifications on :8080, formats them as
Mattermost markdown, and forwards them to a Mattermost incoming webhook.
Python stdlib only; script is mounted from a ConfigMap at /app/relay.py.
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEBHOOK_URL = os.environ["MATTERMOST_WEBHOOK_URL"]
RELAY_TOKEN = os.environ.get("RELAY_TOKEN", "")
PORT = 8080


def format_message(payload: dict) -> str:
    status = payload.get("status", "firing")
    alerts = payload.get("alerts", [])
    icon = ":rotating_light:" if status == "firing" else ":white_check_mark:"
    lines = [f"{icon} **{status.upper()}** — {len(alerts)} alert(s)", ""]
    for alert in alerts:
        labels = alert.get("labels", {})
        name = labels.get("alertname", "unknown")
        severity = labels.get("severity", "none")
        namespace = labels.get("namespace", "-")
        lines.append(f"• **{name}** `[{severity}]` ns=`{namespace}`")
        annotations = alert.get("annotations", {})
        summary = annotations.get("summary")
        if summary:
            lines.append(f"  > {summary}")
    return "\n".join(lines)


def post_mattermost(text: str) -> None:
    request = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        pass


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._send(200, b"ok")
        else:
            self._send(404)

    def do_POST(self):  # noqa: N802
        if RELAY_TOKEN and self.headers.get("Authorization") != f"Bearer {RELAY_TOKEN}":
            self._send(401, b"unauthorized")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            post_mattermost(format_message(payload))
            self._send(200, b"ok")
        except Exception as exc:  # noqa: BLE001 - report and fail closed
            print(f"relay error: {exc}")
            self._send(502, b"upstream error")

    # BaseHTTPRequestHandler.log_message writes to stderr -> pod logs.


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"alertmanager->mattermost relay listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
