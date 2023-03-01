#!/usr/bin/env bash
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

set -eux

# Assuming an lxd controller is already bootstrapped
machine_ctl=$(juju controllers --format json | jq -r '."current-controller"')
# Assuming this shell script is run as part of a pytest test with a model already set up
machine_mdl=$(juju models --format json | jq -r '."current-model"')

if $(groups | grep -q snap_microk8s); then microk8s_group="snap_microk8s"; else microk8s_group="microk8s"; fi

# Assuming there isn't a k8s controller yet
k8s_ctl="uk8s"
k8s_mdl="cos"
sg $microk8s_group -c "juju bootstrap --no-gui microk8s $k8s_ctl"
sg $microk8s_group -c "juju add-model $k8s_mdl"

sg $microk8s_group -c "juju deploy --channel=edge grafana-k8s grafana"
sg $microk8s_group -c "juju offer $k8s_mdl.grafana:grafana-dashboard"

sg $microk8s_group -c "juju switch $machine_ctl:$machine_mdl"
sg $microk8s_group -c "juju consume $k8s_ctl:admin/$k8s_mdl.grafana"

# Assuming kafka was already deployed as part of the pytest test
#charmcraft pack
#juju deploy ./kafka_ubuntu-22.04-amd64.charm kafka
sg $microk8s_group -c "juju relate kafka grafana"

# Now hand over back to the python script
