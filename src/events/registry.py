"""Registry of custom events.

The following custom events are meant to control the execution flow for multiple, simultaneous roles.
"""

from ops import EventBase, EventSource, ObjectEvents


class BalancerInstallEvent(EventBase):
    """Event representing that the balancer should install."""


class BalancerStartEvent(EventBase):
    """Event representing that the balancer should start."""


class BalancerEvents(ObjectEvents):
    """Container for Balancer events."""

    install = EventSource(BalancerInstallEvent)
    start = EventSource(BalancerStartEvent)
