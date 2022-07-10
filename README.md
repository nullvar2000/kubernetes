# kubernetes

initial setup

kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

kubectl -n argocd edit service/argocd-server
  - change Type to LoadBalancer

kubectl -n argocd describe service/argocd-server
  - goto LoadBalancer Ingress IP

kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

kubectl -n argocd apply -f https://raw.githubusercontent.com/nullvar2000/kubernetes/main/argocd/argocd-setup/applicationset.yaml
