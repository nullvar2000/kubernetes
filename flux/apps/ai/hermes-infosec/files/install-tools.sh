#!/bin/sh
# Runs in the alpine install-sops initContainer (agent-files ConfigMap,
# mounted at /seed). Installs pinned sops + kubectl onto the data PVC.
# Idempotent: skips downloads when the pinned binaries already exist.
set -eu

BIN=/opt/data/.local/bin
mkdir -p "$BIN"

install_sops=0
if [ -x "$BIN/sops" ] && "$BIN/sops" --version 2>/dev/null | grep -q 'v3\.13\.3'; then
  echo "sops v3.13.3 already installed"
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
  curl -fsSL -o "$BIN/sops" https://github.com/getsops/sops/releases/download/v3.13.3/sops-v3.13.3.linux.amd64
  chmod 755 "$BIN/sops"
  echo "installed $("$BIN/sops" --version)"
fi

if [ "$install_kubectl" = 1 ]; then
  curl -fsSL -o "$BIN/kubectl" "https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl"
  chmod 755 "$BIN/kubectl"
  echo "installed kubectl v1.35.9"
fi
