# StackRox / ACS (4.11, operator)

Everything except **integrations** is GitOps-managed here. ACS 4.11's declarative
configuration supports only roles, permission sets, access scopes, notifiers, auth
providers, groups and machine-to-machine configs
(`pkg/declarativeconfig/configuration.go`); registry/cluster integrations have no
declarative path, so they live only in `central-db` and must be re-created through
the API after a DB restore/reinstall.

## Registry integrations added imperatively

Images whose registry has no integration are never scanned
(`reprocessor ... Error enriching image ... no matching image registries found:
please add an image integration for <host>`). ACS ships public integrations for
docker.io, gcr.io, ghcr.io, quay.io, mcr.microsoft.com, registry.k8s.io,
public.ecr.aws, registry.access.redhat.com and a few others, but not for
`reg.kyverno.io` or `ecr-public.aws.com`.

Admin credentials for the API: secret `central-htpasswd` in `stackrox`, key `password`.

```bash
kubectl port-forward -n stackrox svc/central 18443:443 &
PW=$(kubectl get secret central-htpasswd -n stackrox -o jsonpath='{.data.password}' | base64 -d)
post() {
  curl -sk -u "admin:$PW" -X POST -H 'Content-Type: application/json' \
    -d "$1" https://localhost:18443/v1/imageintegrations
}
# kyverno (reg.kyverno.io is a GHCR mirror: its anonymous /v2/ ping answers
# 403 {"code":"DENIED"} from ghcr.io/token, so the built-in integration test
# always fails even though pulls/scans work -> skipTestIntegration)
post '{"name":"Public Kyverno Registry","type":"docker","categories":["REGISTRY"],
       "docker":{"endpoint":"reg.kyverno.io","insecure":false},"skipTestIntegration":true}'
# ECR Public gallery under its second hostname (public.ecr.aws is already covered)
post '{"name":"Public ECR (ecr-public.aws.com)","type":"docker","categories":["REGISTRY"],
       "docker":{"endpoint":"ecr-public.aws.com","insecure":false}}'
kill %1
```

Force a scan of a specific image (also useful to verify):

```bash
curl -sk -u "admin:$PW" -X POST -H 'Content-Type: application/json' \
  -d '{"imageName":"reg.kyverno.io/kyverno/kyverno:v1.19.2","force":true}' \
  https://localhost:18443/v1/images/scan
```

Verified 2026-10-31: the four `reg.kyverno.io/kyverno/*:v1.19.2` images index fine
(~340 components each). `ecr-public.aws.com/docker/library/redis:7.2.8-alpine`
still fails on `status=429 TOOMANYREQUESTS` from AWS (anonymous ECR Public pulls are
rate limited); retries land on later reprocessor passes. Referencing the same image
as `docker.io/library/redis:7.2.8-alpine` avoids the anonymous rate limit, since the
"Public DockerHub" integration ships by default.

## Known gaps (not config bugs)

- `scanner.scannerComponent: Disabled` (`central.yaml`): no Kubernetes/Istio
  orchestrator CVEs in 4.11 (only the deprecated legacy Scanner implements
  `OrchestratorScanner`), and System Health keeps showing the two dead legacy
  Scanner rows (`invalid arguments`, `no vulnerability definitions information
  found`; 4.11 hardcodes the legacy scanner as the default in
  `GetVulnDefinitionsInfo`, fixed only in 5.x).
- Node CVEs are empty on Talos: the per-node Scanner V4 index runs in the
  collector `compliance` container and Talos has no package db, so central logs
  `Could not determine operating system from OSimage ref Talos (v1.13.11)` and
  `found 0 components`. The container needs a writable `/tmp` (see the
  `compliance-tmp` overlay in `secured-cluster.yaml`, without which every index
  dies in `internal/rpm: error spooling db ... read-only file system`).
- Nodes without a Collector (cp01-03, s02, s03: no x86-64-v3) keep emitting
  `report "/v4/containerimage/sha256:deadb33f... not found` from
  `sensor/service/pipeline/nodes`; 4.11 has no per-cluster node-scanning switch.
