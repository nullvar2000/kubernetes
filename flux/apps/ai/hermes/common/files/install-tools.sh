#!/bin/sh
# Runs in the alpine install-sops initContainer (agent-files ConfigMap,
# mounted at /seed). Installs pinned sops + kubectl onto the data PVC.
# Idempotent: skips downloads when the pinned binaries already exist.
# Binaries land in a temp file and are moved into place: a target already on
# the PVC may be owned by the agent user (uid 10000), and this container runs
# as root with all capabilities dropped (no CAP_FOWNER), so chmod on such a
# file fails with EPERM.
set -eu

BIN=/opt/data/.local/bin
mkdir -p "$BIN"

# NB sops --version prints "sops 3.13.3 (latest)" — no leading "v".
install_sops=0
if [ -x "$BIN/sops" ] && "$BIN/sops" --version 2>/dev/null | grep -q '^sops 3\.13\.3'; then
  echo "sops 3.13.3 already installed"
else
  install_sops=1
fi

# kubectl is absent from the hermes image; pin to the API server
# minor (Talos reports v1.35.x — verified 2026-11-03 via /version).
install_kubectl=0
if [ -x "$BIN/kubectl" ] && "$BIN/kubectl" version --client -o json 2>/dev/null | grep -q '"gitVersion": "v1\.35\.'; then
  echo "kubectl v1.35.x already installed"
else
  install_kubectl=1
fi

if [ "$install_sops" = 1 ] || [ "$install_kubectl" = 1 ]; then
  apk add --no-cache curl >/dev/null
fi

if [ "$install_sops" = 1 ]; then
  curl -fsSL -o "$BIN/sops.new" https://github.com/getsops/sops/releases/download/v3.13.3/sops-v3.13.3.linux.amd64
  echo "e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b  $BIN/sops.new" | sha256sum -c -
  chmod 755 "$BIN/sops.new"
  mv -f "$BIN/sops.new" "$BIN/sops"
  echo "installed $( "$BIN/sops" --version 2>/dev/null | head -1 )"
fi

if [ "$install_kubectl" = 1 ]; then
  curl -fsSL -o "$BIN/kubectl.new" "https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl"
  echo "3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb  $BIN/kubectl.new" | sha256sum -c -
  chmod 755 "$BIN/kubectl.new"
  mv -f "$BIN/kubectl.new" "$BIN/kubectl"
  echo "installed kubectl v1.35.9"
fi
