#!/usr/bin/env bash
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

# Assuming an lxd controller is already bootstrapped
machine_ctl=$(juju controllers --format json | jq -r '."current-controller"')
# Assuming this shell script is run as part of a pytest test with a model already set up
machine_mdl=$(juju models --format json | jq -r '."current-model"')

# Assuming there isn't a k8s controller yet
k8s_ctl="uk8s"
k8s_mdl="cos"
juju bootstrap --no-gui microk8s "$k8s_ctl"
juju add-model "$k8s_mdl"

juju deploy --channel=edge grafana-k8s grafana
juju offer "$k8s_mdl.grafana:grafana-dashboard"

juju switch "$machine_ctl:$machine_mdl"
juju consume "$k8s_ctl:admin/$k8s_mdl.grafana"

# Assuming kafka was already deployed as part of the pytest test
#charmcraft pack
#juju deploy ./kafka_ubuntu-22.04-amd64.charm kafka
juju relate kafka grafana
