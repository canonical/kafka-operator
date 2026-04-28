#!/bin/bash
# Extracted from : docs/tutorial/manage-passwords.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/manage-passwords.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju show-secret --reveal cluster.kafka.app | yq -r '.[].content["operator-password"]'

_CMD_OUTPUT=$(juju add-secret internal-kafka-users admin=mynewpassword | awk '{print "secret-uri: " $0}')
SECRET_URI=$(echo "$_CMD_OUTPUT" | grep 'secret-uri:' | awk '{print $2}')

juju grant-secret internal-kafka-users kafka

juju config kafka system-users=${SECRET_URI}

juju_wait --timeout 600

juju run data-integrator/leader get-credentials

juju remove-relation kafka data-integrator

juju_wait --timeout 600 --allow-blocked data-integrator

juju integrate kafka data-integrator

juju_wait --timeout 600

juju run data-integrator/leader get-credentials

juju remove-relation kafka data-integrator

juju_wait --timeout 600 --allow-blocked data-integrator
