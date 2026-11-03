#!/bin/sh
# Seed the infosec-engineer Hermes home on first boot. Idempotent.
set -eu
DATA=/opt/data
SEED=/seed

if [ ! -f "$DATA/config.yaml" ]; then
  cp "$SEED/config.yaml.tmpl" "$DATA/config.yaml"
  echo "seeded config.yaml"
fi

if [ ! -f "$DATA/SOUL.md" ]; then
  cp "$SEED/SOUL.md" "$DATA/SOUL.md"
  echo "seeded SOUL.md"
fi

ensure_cron() {
  name="$1"; schedule="$2"; prompt="$3"
  if hermes cron list 2>/dev/null | grep -qi "$name"; then
    echo "cron job '$name' already present"
    return 0
  fi
  # Paused canary: the operator resumes both jobs after first-boot setup
  # (Mattermost home channel + model verification) so pre-dispatch validation
  # does not immediately block on an unconfigured platform.
  hermes cron create "$schedule" "$prompt" \
    --name "$name" --paused \
    --paused-reason "Awaiting first-boot setup (Mattermost + model verification)" \
    || echo "WARN: could not seed cron '$name' (continuing; operator can create it manually)"
}

ensure_cron "pr-security-review" "every 30m" \
  "Run the PR security-review workflow exactly as defined in SOUL.md: /opt/data/.local/bin/gh-review.py pending, then for each listed PR fetch its diff with gh-review.py diff, review it against the SOUL.md policy, and submit the outcome with gh-review.py submit. If pending prints nothing, do nothing and answer 'no PRs in scope'."

ensure_cron "security-signals-digest" "every 30m" \
  "Run the security-signals digest workflow exactly as defined in SOUL.md: read Kyverno ClusterPolicyReports with kubectl and StackRox alerts from the Central REST API, diff against /opt/data/.work/security-signals/ state, triage anything new, update the state files, and report only new/changed findings."

echo "hermes-infosec seed complete"
