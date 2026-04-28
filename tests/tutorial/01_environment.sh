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

# Detect the MTU of the default-route interface (already set by spread allocate).
_iface=$(ip route show default | awk '/default/ {print $5; exit}')
_mtu=$(cat /sys/class/net/"$_iface"/mtu 2>/dev/null || echo 1500)

# Ensure the default bridge exists, disable IPv6 (Juju doesn't support LXD+IPv6),
# and set the MTU to match the host interface.
if ! lxc network show lxdbr0 > /dev/null 2>&1; then
  lxc network create lxdbr0
fi
lxc network set lxdbr0 ipv6.address none
lxc network set lxdbr0 bridge.mtu "$_mtu"
# Tell LXD's dnsmasq on lxdbr0 to forward all queries to Google's resolvers
# so that containers (including the Juju controller) get reliable DNS
# regardless of the state of systemd-resolved on the outer VM.
lxc network set lxdbr0 raw.dnsmasq $'server=8.8.8.8\nserver=8.8.4.4'

# Pin the LXD default profile to lxdbr0 with an explicit MTU.
# This prevents Juju's bootstrap from switching containers to the ubuntu-fan
# overlay network, whose UDP encapsulation would reduce the effective MTU and
# break large snap downloads (e.g. juju-db) inside the controller container.
lxc profile device remove default eth0 2>/dev/null || true
lxc profile device add default eth0 nic nictype=bridged parent=lxdbr0 mtu="$_mtu"

sudo snap install juju || snap list juju

juju bootstrap localhost overlord

lxc list

juju add-model tutorial

# Disable apt update/upgrade during machine provisioning to avoid a known
# apt pipe deadlock bug in Ubuntu 24.04 LXD containers (apt bug #1042290).
juju model-config \
    enable-os-refresh-update=false \
    enable-os-upgrade=false

juju status
