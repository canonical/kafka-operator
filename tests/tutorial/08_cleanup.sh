#!/bin/bash
# Extracted from : docs/tutorial/cleanup.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/cleanup.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

# shellcheck source=tests/tutorial/helpers.sh
. "$SPREAD_PATH/tests/tutorial/helpers.sh"

juju destroy-model tutorial --destroy-storage --force --no-prompt

sleep 120
