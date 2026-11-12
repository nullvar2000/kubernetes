#!/bin/sh
# Seed the agent's Hermes home on first boot. Idempotent. The same script
# serves every hermes overlay: agent identity comes from the per-overlay
# /seed contents (SOUL.md, optional cron-jobs.tsv, config.yaml.tmpl).
set -eu
DATA=/opt/data
SEED=/seed

if [ ! -f "$DATA/config.yaml" ]; then
  cp "$SEED/config.yaml.tmpl" "$DATA/config.yaml"
  echo "seeded config.yaml"
fi

# SOUL.md is git-managed identity: re-copy on every start so reviews/policy
# edits in git take effect on the next pod restart (config.yaml below is NOT
# re-copied — it accumulates imperative runtime state on the PVC).
cp "$SEED/SOUL.md" "$DATA/SOUL.md"
echo "seeded SOUL.md"

# GitOps repo bootstrap for overlays that publish PRs: gated on the GitHub
# App env vars (GH_APP_ID / GH_APP_INSTALLATION_ID / GH_APP_PRIVATE_KEY_B64),
# which only such overlays define; others skip this block entirely. Without
# this, a fresh PVC left the agent with GH_WORKDIR missing and no way to
# work a ticket (observed 2026-11-11). Idempotent with infosec's
# gh-review.py lazy clone: first clone wins, the other sees .git and skips.
# NB: the clone carries an installation token (1h expiry) in its remote URL;
# publishing (gh-pr.py) mints its own fresh token per run, and fetches must
# use `sh /opt/data/.local/bin/git-fetch-origin.sh` which re-mints.
ensure_gitops_repo() {
  [ -n "${GH_APP_ID:-}" ] || return 0
  [ -n "${GH_APP_INSTALLATION_ID:-}" ] || return 0
  [ -n "${GH_APP_PRIVATE_KEY_B64:-}" ] || return 0
  repo="${GH_PR_REPO:-nullvar2000/kubernetes}"
  workdir="${GH_WORKDIR:-/opt/data/k8s-repo}"
  if [ ! -d "$workdir/.git" ]; then
    token=$(python3 "$SEED/gitops-token.py") || {
      echo "WARN: could not mint GitHub App token (skipping gitops clone)"
      return 0
    }
    git clone --filter=blob:none \
      "https://x-access-token:${token}@github.com/${repo}" "$workdir" || {
      echo "WARN: gitops clone failed (continuing)"
      return 0
    }
    git -C "$workdir" remote set-url origin "https://github.com/${repo}"
    echo "cloned gitops repo $repo at $(git -C "$workdir" rev-parse --short HEAD)"
  else
    echo "gitops repo already present at $workdir"
  fi
  mkdir -p "$BIN"
  # copied (not symlinked): /seed is unmounted once the pod is running, and
  # the agent uses these for fetches mid-session.
  cp "$SEED/gitops-token.py" "$SEED/git-fetch-origin.sh" "$BIN/"
}

BIN=/opt/data/.local/bin
ensure_gitops_repo

ensure_cron() {
  name="$1"; schedule="$2"; prompt="$3"
  if hermes cron list 2>/dev/null | grep -qi "$name"; then
    echo "cron job '$name' already present"
    return 0
  fi
  # Paused canary: the operator resumes the jobs after first-boot setup
  # (Mattermost home channel + model verification) so pre-dispatch validation
  # does not immediately block on an unconfigured platform.
  hermes cron create "$schedule" "$prompt" \
    --name "$name" --paused \
    --paused-reason "Awaiting first-boot setup (Mattermost + model verification)" \
    || echo "WARN: could not seed cron '$name' (continuing; operator can create it manually)"
}

# Cron jobs are data, not code: per-overlay /seed/cron-jobs.tsv, one job per
# line, tab-separated name/schedule/prompt (prompts contain spaces, no tabs).
# Overlays without scheduled jobs simply omit the file.
if [ -f "$SEED/cron-jobs.tsv" ]; then
  while IFS="$(printf '\t')" read -r name schedule prompt; do
    [ -n "$name" ] || continue
    ensure_cron "$name" "$schedule" "$prompt"
  done < "$SEED/cron-jobs.tsv"
fi

# This initContainer runs as root (image default) but the gateway/cron
# scheduler drop to the `hermes` user (uid 1000). Root-owned files broke
# every scheduled fire (EACCES on the cron fire-fence locks, incident
# 2026-11-03: jobs silently failed for 21h). Re-own anything root-created,
# including stale contamination from imperative operator execs.
find "$DATA" -user root -exec chown hermes:hermes {} + 2>/dev/null || true

echo "hermes seed complete"
