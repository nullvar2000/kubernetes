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

