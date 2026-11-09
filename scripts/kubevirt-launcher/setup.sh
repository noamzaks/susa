#!/bin/sh
# Prepares a single-node Arm64 cluster for KVMachineModel.emulate and cross_architecture: a local registry, a virt-launcher
# image with QEMU for other architectures, and KubeVirt using it with the CrossArchitectureVirtualization feature gate.
set -e
image=localhost:5000/virt-launcher:v1.9.1-emulators

kubectl apply -f - <<YAML
apiVersion: v1
kind: Namespace
metadata: {name: image-registry}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: registry, namespace: image-registry}
spec:
  replicas: 1
  selector: {matchLabels: {app: registry}}
  template:
    metadata: {labels: {app: registry}}
    spec:
      hostNetwork: true
      containers:
      - name: registry
        image: docker.io/library/registry:2
        env: [{name: REGISTRY_HTTP_ADDR, value: "127.0.0.1:5000"}]
        volumeMounts: [{name: data, mountPath: /var/lib/registry}]
      volumes: [{name: data, emptyDir: {}}]
YAML
kubectl -n image-registry rollout status deployment/registry

podman build -t "$image" "$(dirname "$0")"
podman push --tls-verify=false "$image"

kubectl -n kubevirt patch kubevirt kubevirt --type=json -p \
  '[{"op":"add","path":"/spec/configuration/developerConfiguration/featureGates/-","value":"CrossArchitectureVirtualization"}]'
kubectl -n kubevirt set env deployment/virt-operator "VIRT_LAUNCHER_IMAGE=$image"
