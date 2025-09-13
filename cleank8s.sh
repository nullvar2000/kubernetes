#!/bin/bash

# Get all pods in the default namespace
PODS=$(kubectl get pods -A --no-headers -o custom-columns=":metadata.namespace,:metadata.name,:status.phase")

# Loop through each pod's output
while IFS= read -r POD; do
    # Split the line into pod namespace, name, and container status
    NAMESPACE=$(echo $POD | awk '{print $1}')
    POD_NAME=$(echo $POD | awk '{print $2}')
    STATUS=$(echo $POD | awk '{$1=""; $2=""; print}' | tr -d ' ')

    # Check if the status is "Error" or "ContainerStatusUnknown"
    if [[ "$STATUS" == *"Error"* || "$STATUS" == *"ContainerStatusUnknown"* || "$STATUS" == *"Failed"* ]]; then
        echo "Deleting pod: $POD_NAME"
        kubectl delete pod -n $NAMESPACE $POD_NAME 
    fi
done <<< "$PODS"
