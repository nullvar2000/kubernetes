#!/bin/bash

TAG="44-1"

podman build -t localhost/distrobox/k8s:${TAG}

distrobox create --image localhost/distrobox/k8s:${TAG}

distrobox-export -a codium -d

distrobox-export -a codium
