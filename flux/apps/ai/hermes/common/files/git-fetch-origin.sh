#!/bin/sh
# Fetch origin in the GitOps repo with a freshly-minted GitHub App token.
# The clone's remote URL carries no credentials; a token lasts 1h, so we
# pass it inline per fetch instead of rewriting the remote.
#
# Usage: git-fetch-origin.sh [refspec...]   (default: all branches)
set -eu
repo="${GH_PR_REPO:-nullvar2000/kubernetes}"
workdir="${GH_WORKDIR:-/opt/data/k8s-repo}"
token=$(python3 /opt/data/.local/bin/gitops-token.py) || exit 1
if [ "$#" -gt 0 ]; then
  git -C "$workdir" fetch "https://x-access-token:${token}@github.com/${repo}" "$@"
else
  git -C "$workdir" fetch --prune "https://x-access-token:${token}@github.com/${repo}" \
    '+refs/heads/*:refs/remotes/origin/*'
fi
