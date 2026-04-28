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

# Ensure the default bridge exists with a path-MTU-safe MTU (1492 for PPPoE
# upstreams) and without IPv6 (Juju doesn't support LXD+IPv6).
if ! lxc network show lxdbr0 > /dev/null 2>&1; then
  lxc network create lxdbr0
fi
lxc network set lxdbr0 ipv6.address none
lxc network set lxdbr0 bridge.mtu 1492

sudo snap install juju || snap list juju

juju bootstrap localhost overlord

lxc list

juju add-model tutorial

juju status
