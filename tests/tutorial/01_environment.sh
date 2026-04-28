#!/bin/bash
# Extracted from : docs/tutorial/environment.md
# Regenerate with: python3 tests/tutorial/extract_commands.py docs/tutorial/environment.md <output.sh>
#
# To skip a block in the Markdown source, add this comment on the line
# immediately before its opening fence (blank lines are fine between them):
#   <!-- test:skip -->
#
# Only ```shell fences are extracted; use any other tag to naturally exclude a block.

set -euo pipefail

lxd init --auto
lxc network set lxdbr0 ipv6.address none

sudo snap install juju

juju bootstrap localhost overlord

lxc list

juju add-model tutorial

juju status
