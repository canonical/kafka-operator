#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling KIP-714 client metrics subscriptions."""

import logging
import re
from dataclasses import dataclass

from ..core.cluster import KafkaContext
from ..core.workload import WorkloadBase

logger = logging.getLogger(__name__)

CLIENT_METRICS_ENTITY_TYPE = "client-metrics"
INTERVAL_MS_CONFIG = "interval.ms"
METRICS_CONFIG = "metrics"

# e.g. "Dynamic configs for client-metric producer-metrics are:"
RESOURCE_PATTERN = re.compile(r"configs for client-metric (?P<name>\S+) are:")
# e.g. "  interval.ms=1000 sensitive=false synonyms={...}"
CONFIG_PATTERN = re.compile(r"^\s+(?P<key>[^=\s]+)=(?P<value>\S*)")


@dataclass(frozen=True)
class ClientMetricsSubscription:
    """Convenience object for representing a KIP-714 client metrics subscription.

    An empty `metric_name` is the KIP-714 wildcard, i.e. all client metrics are subscribed to.
    """

    metric_name: str
    interval_ms: int


class ClientMetricsManager:
    """Object for handling KIP-714 client metrics subscriptions.

    Each subscription is managed as a single client metrics resource named after the metric
    prefix it subscribes to, i.e. `metric_name` is used as both the `--entity-name` and the
    `metrics` config of the resource.
    """

    def __init__(self, state: KafkaContext, workload: WorkloadBase):
        self.state = state
        self.workload = workload

    @property
    def current_subscriptions(self) -> list[ClientMetricsSubscription]:
        """The client metrics subscriptions currently active on the cluster."""
        return self._parse_subscriptions(self._get_subscriptions_from_cluster())

    def add_subscription(self, metric_name: str, interval: int) -> None:
        """Adds or updates the cluster subscription for a given metric prefix.

        Args:
            metric_name: the client telemetry metric name prefix to subscribe to
            interval: the push interval in milliseconds

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        logger.info(f"Adding client metrics subscription for {metric_name}")
        self._alter_subscription(
            metric_name,
            [f"--add-config {INTERVAL_MS_CONFIG}={interval},{METRICS_CONFIG}={metric_name}"],
        )

    def remove_subscription(self, metric_name: str) -> None:
        """Removes the cluster subscription for a given metric prefix.

        Args:
            metric_name: the client telemetry metric name prefix to unsubscribe from

        Raises:
            `(subprocess.CalledProcessError | ops.pebble.ExecError)`: if the error returned a non-zero exit code
        """
        logger.info(f"Removing client metrics subscription for {metric_name}")
        self._alter_subscription(
            metric_name, [f"--delete-config {INTERVAL_MS_CONFIG},{METRICS_CONFIG}"]
        )

    def _get_subscriptions_from_cluster(self) -> str:
        """Loads the currently configured client metrics resources from the Kafka cluster."""
        return self._run_configs_command(["--describe"])

    def _alter_subscription(self, metric_name: str, bin_args: list[str]) -> None:
        """Alters the client metrics resource of a given metric prefix."""
        self._run_configs_command([f"--entity-name {metric_name}", "--alter"] + bin_args)

    def _run_configs_command(self, bin_args: list[str]) -> str:
        """Runs a `kafka-configs` command scoped to the client metrics entity type."""
        common_args = [
            f"--bootstrap-server {self.state.bootstrap_server_internal}",
            f"--command-config {self.workload.paths.client_properties}",
            f"--entity-type {CLIENT_METRICS_ENTITY_TYPE}",
        ]

        return self.workload.run_bin_command(
            bin_keyword="configs", bin_args=common_args + bin_args
        )

    @staticmethod
    def _parse_subscriptions(subscriptions: str) -> list[ClientMetricsSubscription]:
        """Parses output from raw client metrics configs provided by the cluster.

        A single client metrics resource may subscribe to several metric prefixes, in which case
        one `ClientMetricsSubscription` per prefix is returned, all sharing the resource interval.
        """
        resources: dict[str, dict[str, str]] = {}
        current_configs: dict[str, str] | None = None

        for line in subscriptions.splitlines():
            if resource_match := RESOURCE_PATTERN.search(line):
                current_configs = resources.setdefault(resource_match.group("name"), {})
                continue

            if current_configs is None:
                continue

            if config_match := CONFIG_PATTERN.match(line):
                current_configs[config_match.group("key")] = config_match.group("value")

        parsed: list[ClientMetricsSubscription] = []
        for name, configs in resources.items():
            try:
                interval_ms = int(configs[INTERVAL_MS_CONFIG])
            except (KeyError, ValueError):
                logger.warning(
                    f"client-metric {name} has no valid {INTERVAL_MS_CONFIG} config, skipping..."
                )
                continue

            parsed += [
                ClientMetricsSubscription(metric_name=metric_name, interval_ms=interval_ms)
                for metric_name in configs.get(METRICS_CONFIG, "").split(",")
            ]

        return parsed
