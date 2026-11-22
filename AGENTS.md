# AGENTS.md

GitOps repo for a home Talos cluster (kingperch.xyz; 3 control-plane, 4 storage, 3 worker, 1 GPU node). This is NOT Kubernetes source — it is the single source of cluster state. Changes = edit manifests + push to `main`; Flux syncs within ~1 minute. There is no application code, build step, or test suite.

## Sync topology

- Flux self-bootstrap: `flux/clusters/home/flux-system/gotk-sync.yaml` → path `./flux/clusters/home`
- `flux/clusters/home/apps.yaml` → `./flux/apps`; `flux/clusters/home/infrastructure.yaml` → `./flux/infrastructure`. Both run `prune: true`, sops decryption, and `${VAR}` substitution from `global-secrets` plus their own secrets (`apps-secrets` / `infrastructure-secrets`)
- ArgoCD ApplicationSet (`argocd/appsets/core.yaml`) auto-creates one Application per directory under `argocd/core/*` (app name = namespace = dir basename); core apps are synced manually (automation is commented out in the template). One-time bootstrap is in the README (helm install + `argocd/setup.yaml`)

## Secrets — read before touching any value

- age key: `~/.sops/key.txt` (recipient in `flux/.sops.yaml`); cluster-side key: `sops-age` secret in `flux-system`
- Tracked: `*.sops.yaml` (encrypted) and `secrets.clear.yaml` (templates — contain ONLY `${VAR}` placeholders, never real values)
- Local-only, gitignored, NEVER commit: `flux/clusters/home/global-secrets.yaml`, `flux/apps/apps-secrets.yaml`, `flux/infrastructure/infrastructure-secrets.yaml`
- Change a value: edit the local plaintext `*-secrets.yaml` → `sops -e <file> > <file>.sops.yaml` → commit only the `.sops.yaml`
- `apps-secrets` and `infrastructure-secrets` are Flux-managed (their sops manifests are inside the synced trees). `global-secrets` is NOT in any kustomization — apply it manually after decrypting: `sops -d flux/clusters/home/global-secrets.sops.yaml | kubectl apply -n flux-system -f -`
- Variable naming: `GLOBAL_*` for globals; app-scoped vars prefixed with upper-cased app name (`AI_LITELLM_*`, `MATTERMOST_*`)
- Substitution happens only in Flux (postBuild.substituteFrom). A local `kubectl kustomize` build succeeds with unknown `${VAR}` left as literal strings — it will NOT catch a missing secret
- Flux envsub is NON-STRICT: EVERY unrecognized `${...}` in the rendered tree (including inside ConfigMap-embedded scripts, templates, and even comments) is replaced with the empty string. Any ConfigMap embedding shell/Python/tool `${...}` literals must carry `kustomize.toolkit.fluxcd.io/substitute: disabled` (set it on every configMapGenerator declaration incl. `behavior: merge`; kustomize-controller skips that resource). Symptom seen 2026-11-12: hermes `agent-files`/`agent-scripts` silently gutted (`Bearer ` header, `[ -n "" ]` guards)
- sops gotcha: sops finds `.sops.yaml` (creation rules) by walking up from the **current working directory**, not the file path. Run `sops -e`/`sops -d` from inside `flux/` (e.g. `cd flux/apps`) or it fails with "config file not found"
- Quote all secret values in the plaintext `*-secrets.yaml` (e.g. `FOO: "12345"`). Bare numbers are parsed as YAML ints and break Flux postBuild / ConfigMap typing (`expected string, got int`)
- New-variable chicken-and-egg: if a PR introduces a `${VAR}` not yet in the cluster's `apps-secrets`/`infrastructure-secrets` Secret, `flux-apps`/`flux-infrastructure` fail postBuild (the missing var substitutes to an empty string) and never apply the updated Secret themselves. Break it with a one-time manual apply from the PR: `sops -d flux/apps/apps-secrets.sops.yaml | kubectl apply -n flux-system -f -`

## Conventions

- Disabling a component = rename its manifest to `*.disabled` (gitignored), which removes it from the repo and prunes it from the cluster (e.g. `ollama-rocm.disabled`)
- New Flux app: directory under `flux/apps/...` with `kustomization.yaml`, `namespace.yaml`, workload, `service.yaml`, `httproute.yaml` (Gateway API, not Ingress), `imageupdateautomation.yaml`, optional `secrets.clear.yaml` and `files/`; register the dir in the parent `kustomization.yaml`
- Image updates: each app's `imageupdateautomation.yaml` (resources live in `flux-system`) pushes tag bumps to a `fluxcd-<name>-image-update` branch with commit message `<old-image> -> <new-image>` (author fluxcdbot). These land on main via PR merge — do not push tag changes directly to main; follow the same branch + message format when bumping manually
- `toolbox/` is a distrobox dev image (fedora-toolbox + kubectl, talosctl, helm, flux, sops, age, codium); `toolbox/build.sh` rebuilds it. Only `kubectl` is symlinked onto the host PATH; run the others as `distrobox enter k8s44-1 -- <tool> ...` (e.g. `distrobox enter k8s44-1 -- flux reconcile kustomization flux-apps -n flux-system`)
- `hosts/` = out-of-cluster host infrastructure (e.g. `hosts/comfyui/`: ComfyUI + MCP-gateway image and compose for 192.168.30.254). NOT Flux-synced — the repo files are the source of truth, applied manually on the target host (see each dir's README)
- `venv/` and `tmp/` are local scratch, not project content. `cleank8s.sh` deletes pods in Error/Failed/Unknown phase

## Lab TODO (BookStack)

- Permanent cluster/lab TODO list: BookStack page `lab-ops/cluster-todo` (book "Lab Ops", page id 5) — at wiki.kingperch.xyz, writable via the litellm bookstack MCP (`bookstack_pages_append` / `bookstack_pages_edit`)
- Any agent may append items under **Next** and change statuses (tick/move to Done after completing work) but must never delete items or restructure the page — pruning is human-only
- Read the page's House-rules block before writing (entry format, area tags); never put secrets on the page (wiki + mcp-wiki are on the public gateway)
- hermes agents still lack the bookstack MCP mount (see the tracked item on the page itself); opencode has it via litellm

## Implementation agent (platform-engineer)

- Approved plans (from k8s-architect or the user) are executed by the **platform-engineer** agent: a Hermes Agent running in-cluster (namespace `hermes-platform-engineer`, pod `hermes-0`; StatefulSet `hermes` from `flux/apps/ai/hermes/common` + the platform-engineer overlay), reached over the A2A protocol through the LiteLLM JSON-RPC passthrough (`POST https://litellm.kingperch.xyz/a2a/platform-engineer`). The opencode subagent `.opencode/agents/platform-engineer.md` is a thin client that wraps `~/.local/bin/k8s-a2a` (send → poll `tasks/list` by contextId; `message/send` blocks upstream for up to 30 min so the wrapper polls).
- Two git clones in the pod (verified 2026-11-19): the **edit clone is `/opt/data/work/k8s-work`** (agent-created `--filter=blob:none` partial clone; all branches/commits for PRs happen here — the agent verifies builds, commits on branch `platform-engineer/<date>-<slug>`, publishes the PR, then alerts Mattermost); the **seed clone is `/opt/data/k8s-repo`** (`GH_WORKDIR`, cloned by seed.sh at first boot, then its remote normalized to a credential-less URL — it can sit days stale, do NOT edit there and do not read it for current state).
- Freshness: the edit clone syncs to `origin/main` before each task (recent PRs provably branch off current main: #560 @ `577e971e`, #561 @ `ad10c5b2`). `git-fetch-origin.sh` re-mints a GitHub App token per fetch; its default workdir is the SEED clone — sync the EDIT clone with `GIT_FETCH_WORKDIR=/opt/data/work/k8s-work git-fetch-origin.sh`.
- Publishing/scratch: `gh-pr.py` mints a 1h installation token per PR (no long-lived creds); install-tools.sh normalizes any `x-access-token`-bearing remote URL in the edit clone's `.git/config` on every pod start (infosec advisory on #575 closed 2026-11-21). Scratch output (PR bodies, `pr<N>.json`) lands in `/opt/data/cache/scratch/`. The agent's pod SA has `pods/get/log` but **not** `pods/exec`, so it can't read another pod's live config — verify cluster state with `kubectl get/describe/logs`/`flux get ks` only.
- **Nothing is applied until the PR is reviewed and merged** — merging is the human gate. Flux syncs main as usual afterwards.
- In-pod sops uses the cluster age key: `kubectl get secret sops-age -n flux-system` (data key `age.agekey`), readable with the pod's view RBAC. The workstation key is NOT in the pod.
- If the plan adds a new secret variable, the PR body + Mattermost alert flag the one-time manual apply (see the chicken-and-egg note above) — the operator runs it before/after merging.
- In-pod CLIs need full paths: the hermes terminal sandbox resets PATH despite agent.env setting it — call `/opt/data/.local/bin/{kubectl,flux,sops}`. The PE ClusterRole intentionally excludes the security-audit surface (kyverno/policies.kyverno.io/wgpolicyk8s.io/admissionregistration/apiextensions/stackrox): route those verification steps to the hermes-infosec agent or the workstation; its RBAC mirror invariant (`kubernetes-mcp-infosec`) covers the infosec side.

## Verification (no test suite)

- `kubectl kustomize flux/apps/<app>` — structural check. Standalone `kustomize` is not installed; use relative paths (absolute paths fail with an evalsymlink error)
- `sops -d flux/apps/apps-secrets.sops.yaml` — confirms the age key works locally
- Cluster: `kubectl get kustomization -n flux-system` (READY column), `flux get ks -A`, `kubectl get application -n argocd`, `kubectl get pods -A`
- Only cluster sync validates sops decryption + `${VAR}` substitution end-to-end
