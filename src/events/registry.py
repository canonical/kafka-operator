"""Registry of custom events.

The following custom events are meant to control the execution flow for multiple, simultaneous roles.
"""

from ops import EventBase, EventSource, ObjectEvents


class BalancerStartEvent(EventBase):
    """Event representing that the balancer should start."""


class BalancerEvents(ObjectEvents):
    """Container for Balancer events."""

    start = EventSource(BalancerStartEvent)


class BrokerConfigChangedEvent(EventBase):
    """Event representing that the broker configuration changed."""


class BrokerUpdateStatusEvent(EventBase):
    """Event representing that the broker should update its status."""


class BrokerEvents(ObjectEvents):
    """Container for Broker events."""

    config_changed = EventSource(BrokerConfigChangedEvent)
    update_status = EventSource(BrokerUpdateStatusEvent)
