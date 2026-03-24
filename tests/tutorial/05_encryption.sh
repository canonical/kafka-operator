#!/bin/bash
# Extracted from : docs/tutorial/enable-encryption.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/enable-encryption.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"

juju_wait --timeout 600

juju integrate kafka:certificates self-signed-certificates

juju_wait --timeout 600

juju integrate data-integrator kafka

juju_wait --timeout 600

juju deploy kafka-test-app --channel edge

juju_wait --timeout 600

juju integrate kafka-test-app self-signed-certificates

juju_wait --timeout 300

juju config kafka-test-app topic_name=HOT-TOPIC role=producer num_messages=20

juju integrate kafka kafka-test-app

juju_wait --timeout 600

juju exec --application kafka-test-app "tail /tmp/*.log"

juju remove-relation kafka self-signed-certificates

juju_wait --timeout 600

juju remove-relation kafka-test-app kafka
juju remove-relation kafka-test-app self-signed-certificates
juju remove-application kafka-test-app --destroy-storage

juju_wait --timeout 600
