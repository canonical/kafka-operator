#!/bin/bash
# Extracted from : docs/tutorial/deploy.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/deploy.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju deploy kafka -n 3 --channel 4/edge --config roles=broker

juju deploy kafka -n 3 --channel 4/edge --config roles=controller kraft

juju integrate kafka:peer-cluster-orchestrator kraft:peer-cluster

# Wait for all 6 units (3 brokers + 3 controllers) to reach active/idle.
juju_wait --timeout 1800

juju show-secret --reveal cluster.kafka.app

juju show-secret --reveal cluster.kafka.app | yq -r '.[].content["operator-password"]'

bootstrap_address=$(juju show-unit kafka/0 | yq '.. | ."public-address"? // ""' | tr -d '"' | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

export BOOTSTRAP_SERVER="${bootstrap_address}:19093"

juju ssh kafka/leader sudo -i "ls \$BIN/bin"

juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --create \
        --topic test-topic \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"

juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --list \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"

juju ssh kafka/0 sudo -i \
    "charmed-kafka.topics \
        --delete \
        --topic test-topic \
        --bootstrap-server $BOOTSTRAP_SERVER \
        --command-config \$CONF/client.properties"
