# kubernetes

initial setup
```
kubectl create namespace argocd
helm install argo-cd argo/argo-cd --namespace argocd
```

kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

kubectl -n argocd apply -f https://raw.githubusercontent.com/nullvar2000/kubernetes/main/argocd/setup.yaml

# sops
[Flux SOPS Guide](https://fluxcd.io/flux/guides/mozilla-sops/)

Create keys:
```
age-keygen -o $HOME/.sops/key.txt
```

One time cluster setup:
```
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey=$HOME/.sops/key.txt
```

encrypt:
```
sops -e clusters/home/global-secrets.yaml > clusters/home/global-secrets.sops.yaml
```

decrypt:
```
sops -d clusters/home/global-secrets.sops.yaml
```
