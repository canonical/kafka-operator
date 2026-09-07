#!/bin/bash

set -Eeuo pipefail

chaos_mesh_ns=$1
chaos_mesh_version="2.4.1"

if [ -z "${chaos_mesh_ns}" ]; then
	echo "Error: missing mandatory argument. Aborting" >&2
	exit 1
fi

# Check if microk8s is available
if command -v microk8s.helm3 >/dev/null 2>&1; then
  helm_cmd="microk8s.helm3"
  socket_path=/var/snap/microk8s/common/run/containerd.sock
else
  helm_cmd="k8s helm"
  socket_path=/run/containerd/containerd.sock
fi

deploy_chaos_mesh() {
	echo "adding chaos-mesh helm repo"
	$helm_cmd repo add chaos-mesh https://charts.chaos-mesh.org

	echo "installing chaos-mesh"
        $helm_cmd install chaos-mesh chaos-mesh/chaos-mesh \
          --namespace="${chaos_mesh_ns}" \
          --set chaosDaemon.runtime=containerd \
          --set chaosDaemon.socketPath="$socket_path" \
          --set dashboard.create=false \
          --version "${chaos_mesh_version}" \
          --set clusterScoped=false \
          --set controllerManager.targetNamespace="${chaos_mesh_ns}"

	sleep 10
}

echo "namespace=${chaos_mesh_ns}"
deploy_chaos_mesh
