#!/usr/bin/env python3
"""StackRox Central read-only plumbing for the infosec-engineer agent.

Fetches security alerts from StackRox Central over the in-cluster service DNS
name, writes the full payload under /opt/data/.work/, prints a compact summary,
and maintains the security-signals-digest state file. Deterministic plumbing;
the triage is the agent's job.

Why a script rather than a curl recipe in SOUL.md: that recipe (Bearer token
header + `-k` against an https URL) matched hermes' prompt-injection detector
(`exfil_curl`) on every session start — the security agent's own trusted
context file read as credential exfiltration. The token now lives only in the
process environment and the agent invokes a named tool.

Usage:
    stackrox-alerts.py alerts [--limit N] [--out PATH]
    stackrox-alerts.py snapshot [--limit N]
    stackrox-alerts.py raw <path> [--out PATH]

    alerts    GET /v1/alerts, print severity counts + the newest entries, and
              write the full payload to PATH (default
              /opt/data/.work/stackrox/alerts-<UTC stamp>.json)
    snapshot  fetch alerts, rewrite the digest state file (--state, default
              /opt/data/.work/security-signals/stackrox.json), and print only
              the alert ids that are new or gone since the previous run
    raw       GET one /v1/... Central path (no scheme, no host, GET only) and
              write it to PATH

Env (already present in the container; this script never prints them):
    STACKROX_API_URL   e.g. https://central.stackrox.svc.cluster.local:443
    STACKROX_API_TOKEN read-only Central API token
"""
import argparse
import datetime
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

WORK = "/opt/data/.work/stackrox"
DEFAULT_STATE = "/opt/data/.work/security-signals/stackrox.json"
SUMMARY_ROWS = 15

# Central serves a self-signed cert in-cluster (flux/infrastructure/stackrox/
# cert.yaml + central-backend-tls-dr.yaml), and the service DNS name is not in
# its SAN set — so verification is off, exactly like the `curl -k` this script
# replaces. Scope is deliberately narrow: GET only, fixed in-cluster host.
CTX = ssl._create_unverified_context()


def env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"stackrox-alerts: missing required env var {name}")
    return value


def get(path):
    url = f"{env('STACKROX_API_URL').rstrip('/')}{path}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {env('STACKROX_API_TOKEN')}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, context=CTX, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        # Central's error bodies do not echo the token; safe to surface.
        body = exc.read().decode("utf-8", "replace")[:2000]
        sys.exit(f"stackrox-alerts: GET {path} -> HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        sys.exit(
            f"stackrox-alerts: GET {path} -> {exc.reason} "
            "(is central.stackrox.svc up, and is STACKROX_API_URL correct?)"
        )


def write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def alerts_query(limit):
    return urllib.parse.urlencode(
        {"limit": limit, "sort": "TIME", "ascending": "false"}
    )


def normalise(payload):
    """Trim Central's alert objects to the fields the digest reports on."""
    rows = []
    for item in payload.get("items") or []:
        rows.append(
            {
                "id": item.get("id"),
                "policy": item.get("policy"),
                "severity": item.get("severity"),
                "deployment": (item.get("deployment") or {}).get("name"),
                "time": item.get("time") or "",
            }
        )
    rows.sort(key=lambda row: row.get("id") or "")
    return rows


def cmd_alerts(args):
    payload = get(f"/v1/alerts?{alerts_query(args.limit)}")
    out = write(args.out or os.path.join(WORK, f"alerts-{stamp()}.json"), payload)
    rows = normalise(payload)
    counts = {}
    for row in rows:
        key = row["severity"] or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    print(f"alerts: {len(rows)} returned (limit {args.limit}); by severity: "
          f"{json.dumps(counts, sort_keys=True)}")
    for row in rows[:SUMMARY_ROWS]:
        print(f"  {row['time']} {str(row['severity']):<8} "
              f"{row['deployment']} :: {row['policy']}")
    print(f"full payload: {out}")


def cmd_snapshot(args):
    rows = normalise(get(f"/v1/alerts?{alerts_query(args.limit)}"))
    previous = []
    if os.path.exists(args.state):
        with open(args.state) as handle:
            previous = json.load(handle)
    before = {row.get("id") for row in previous}
    now = {row["id"] for row in rows}
    write(args.state, rows)
    print(f"state: {args.state} ({len(rows)} alerts)")
    print(f"new ({len(now - before)}): {json.dumps(sorted(now - before))}")
    print(f"gone ({len(before - now)}): {json.dumps(sorted(before - now))}")


def cmd_raw(args):
    if "://" in args.path or not args.path.startswith("/v1/"):
        sys.exit("stackrox-alerts: raw takes a path starting /v1/ — no scheme, "
                 "no host; the target stays the in-cluster service")
    payload = get(args.path)
    slug = args.path.strip("/").replace("/", "_")
    out = write(args.out or os.path.join(WORK, f"raw-{slug}-{stamp()}.json"), payload)
    print(f"wrote {out}")
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            print(f"items: {len(items)}")
        else:
            print(f"keys: {sorted(payload)[:20]}")


def main():
    parser = argparse.ArgumentParser(prog="stackrox-alerts")
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help="digest state file (snapshot subcommand)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_alerts = sub.add_parser("alerts", help="fetch alerts, print a summary")
    p_alerts.add_argument("--limit", type=int, default=50)
    p_alerts.add_argument("--out", help="where to write the payload")

    p_snap = sub.add_parser("snapshot", help="fetch + update state, print a diff")
    p_snap.add_argument("--limit", type=int, default=200)

    p_raw = sub.add_parser("raw", help="GET one /v1/... path")
    p_raw.add_argument("path")
    p_raw.add_argument("--out", help="where to write the payload")

    args = parser.parse_args()
    {"alerts": cmd_alerts, "snapshot": cmd_snapshot, "raw": cmd_raw}[args.cmd](args)


if __name__ == "__main__":
    main()
