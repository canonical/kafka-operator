#!/bin/bash
# Extracted from : docs/tutorial/integrate-with-client-applications.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/integrate-with-client-applications.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju deploy data-integrator --config topic-name=test-topic --config extra-user-roles=producer,consumer

juju integrate data-integrator kafka

juju_wait --timeout 300

juju run data-integrator/leader get-credentials

juju deploy kafka-test-app --channel edge

juju config kafka-test-app topic_name=TOP-PICK role=producer num_messages=20

juju integrate kafka-test-app kafka

juju_wait --timeout 300

juju status

juju exec --application kafka-test-app "tail /tmp/*.log"

juju remove-relation kafka-test-app kafka

juju config kafka-test-app topic_name=TOP-PICK role=consumer consumer_group_prefix=cg

juju integrate kafka-test-app kafka

juju_wait --timeout 300

juju remove-relation kafka-test-app kafka
juju remove-application kafka-test-app --destroy-storage
