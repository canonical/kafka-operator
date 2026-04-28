#!/bin/bash
# Extracted from : docs/tutorial/rebalance-partitions.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/rebalance-partitions.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju config kraft roles=balancer,controller

juju_wait --timeout 1200

juju add-unit kafka

juju_wait --timeout 1200

_CMD_OUTPUT=$(juju show-unit kafka/0 --format json | jq -r '."kafka/0"."public-address"' | awk '{print "unit-ip: " $1}')
KAFKA_UNIT_IP=$(echo "$_CMD_OUTPUT" | grep 'unit-ip:' | awk '{print $2}')

juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server ${KAFKA_UNIT_IP}:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'

sleep 1200

( timeout 180 bash << 'TUTORIAL_TIMEOUT_EOF'
juju run kraft/leader rebalance mode=add brokerid=103 --wait=2m
TUTORIAL_TIMEOUT_EOF
) || true

juju run kraft/leader rebalance mode=add dryrun=false brokerid=103 --wait=10m

juju_wait --timeout 1200

juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server ${KAFKA_UNIT_IP}:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'

juju run kraft/leader rebalance mode=remove dryrun=false brokerid=3 --wait=10m

juju_wait --timeout 1200

juju ssh kafka/leader sudo -i charmed-kafka.log-dirs --describe \
  --bootstrap-server ${KAFKA_UNIT_IP}:19093 \
  --command-config '$CONF/client.properties' \
  2>/dev/null \
  | sed -n '/^{/p' \
  | jq '.brokers[] | select(.broker == 103)'

juju remove-unit kafka/3 --no-prompt

juju_wait --timeout 1200

( timeout 660 bash << 'TUTORIAL_TIMEOUT_EOF'
juju run kraft/leader rebalance mode=full --wait=10m
TUTORIAL_TIMEOUT_EOF
) || true

juju run kraft/leader rebalance mode=full dryrun=false --wait=10m
