#!/bin/sh
# Runs in the alpine install-tools initContainer (agent-files ConfigMap,
# mounted at /seed). Installs pinned sops + kubectl + flux onto the data PVC
# and repairs sandbox leftovers. Idempotent: skips downloads when the pinned
# binaries already exist.
# Binaries land in a temp file and are moved into place: a target already on
# the PVC may be owned by the agent user (uid 10000), and this container runs
# as root with ALL capabilities dropped EXCEPT CHOWN/FOWNER/DAC_OVERRIDE (granted in the
# StatefulSet 2026-11-18 so the ownership repair below can work at all).
set -eu

BIN=/opt/data/.local/bin
mkdir -p "$BIN"

# --- sandbox leftovers repair (root-owned files are created by the hermes
# terminal sandbox's uid remap; seed.sh's chown self-repair is a silent no-op
# because seed-agent drops ALL caps) -------------------------------------
# Ghost kubeconfigs are poison: kubectl prefers $HOME/.kube/config and fails
# instead of falling back to the projected SA token (in-cluster auth).
# Nothing in the GitOps repo ever creates them — always leftovers, always safe
# to remove.
rm -rf /opt/data/home/.kube /opt/data/.kube 2>/dev/null || true
chown -R 10000:10000 "$BIN" /opt/data/home 2>/dev/null || true

# Credential-less-remote invariant for the EDIT clone (infosec advisory on #575,
# 2026-11-21): ad-hoc clones made with an inline minted GitHub App token URL
# persist it in .git/config. The token expires in ~1h (inert), but we keep the
# same no-credentials-in-remotes pattern seed.sh enforces for the seed clone.
# busybox sed (alpine) edits .git/config directly; the pattern matches ONLY the
# x-access-token URL form. Needs DAC_OVERRIDE (the clone is hermes-owned).
if [ -f /opt/data/work/k8s-work/.git/config ]; then
  sed -i 's#https://x-access-token:[^@]*@github\.com/#https://github.com/#g' \
    /opt/data/work/k8s-work/.git/config && echo "normalized edit-clone remote"
fi

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

# flux CLI is absent too; pin to the cluster's controller series (gotk:
# source-controller v1.7.4 / kustomize v1.7.3 / helm v1.4.5 => Flux v2.7.x,
# newest patch v2.7.5). Needed for `flux get ks/hr/sources` verification runs.
install_flux=0
if [ -x "$BIN/flux" ] && "$BIN/flux" --version 2>/dev/null | grep -q 'flux version 2\.7\.5'; then
  echo "flux v2.7.5 already installed"
else
  install_flux=1
fi

if [ "$install_sops" = 1 ] || [ "$install_kubectl" = 1 ] || [ "$install_flux" = 1 ]; then
  apk add --no-cache curl tar >/dev/null
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

if [ "$install_flux" = 1 ]; then
  curl -fsSL -o /tmp/flux.tgz "https://github.com/fluxcd/flux2/releases/download/v2.7.5/flux_2.7.5_linux_amd64.tar.gz"
  echo "1e92141e8498289e4b27411385aeb18396053176cf297b0cb99abd6ca8293e75  /tmp/flux.tgz" | sha256sum -c -
  tar -xzf /tmp/flux.tgz -C /tmp
  chmod 755 /tmp/flux
  mv -f /tmp/flux "$BIN/flux"
  rm -f /tmp/flux.tgz
  echo "installed $( "$BIN/flux" --version 2>/dev/null | head -1 )"
fi
