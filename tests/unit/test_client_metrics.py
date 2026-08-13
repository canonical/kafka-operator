#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test cases for parsing KIP-714 client metrics subscriptions."""

import logging
from unittest.mock import MagicMock

import pytest
from charmlibs import pathops
from common.single_kernel_kafka.core.literals import BROKER
from common.single_kernel_kafka.core.workload import CharmedKafkaPaths, WorkloadBase
from common.single_kernel_kafka.managers.client_metrics import (
    ClientMetricsManager,
    ClientMetricsSubscription,
)
from tests.unit.helpers import SUBSTRATE

logger = logging.getLogger(__name__)
pytestmark = [
    pytest.mark.skipif(
        SUBSTRATE == "k8s", reason="No need to run substrate-agnostic tests on K8s."
    )
]

BOOTSTRAP_SERVER = "10.10.10.10:9092"


@pytest.fixture()
def fake_workload(tmp_path_factory) -> WorkloadBase:
    workload = MagicMock(spec=WorkloadBase)
    workload.root = pathops.LocalPath("/")
    workload.paths = CharmedKafkaPaths(BROKER)
    workload.paths.conf_path = tmp_path_factory.mktemp("workload")
    return workload


@pytest.fixture()
def manager(fake_workload) -> ClientMetricsManager:
    state = MagicMock()
    state.bootstrap_server_internal = BOOTSTRAP_SERVER
    return ClientMetricsManager(state=state, workload=fake_workload)


DESCRIBE_OUTPUT = """Dynamic configs for client-metric producer-metrics are:
  interval.ms=1000 sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:interval.ms=1000}
  metrics=org.apache.kafka.producer. sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:metrics=org.apache.kafka.producer.}
Dynamic configs for client-metric consumer-metrics are:
  interval.ms=2000 sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:interval.ms=2000}
  metrics=org.apache.kafka.consumer. sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:metrics=org.apache.kafka.consumer.}
"""


def test_parse_subscriptions():
    assert ClientMetricsManager._parse_subscriptions(DESCRIBE_OUTPUT) == [
        ClientMetricsSubscription(metric_name="org.apache.kafka.producer.", interval_ms=1000),
        ClientMetricsSubscription(metric_name="org.apache.kafka.consumer.", interval_ms=2000),
    ]


def test_parse_subscriptions_empty_output():
    assert ClientMetricsManager._parse_subscriptions("") == []


def test_parse_subscriptions_multiple_metrics_per_resource():
    raw = (
        "Dynamic configs for client-metric all-metrics are:\n"
        "  interval.ms=5000 sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:interval.ms=5000}\n"
        "  metrics=org.apache.kafka.producer.,org.apache.kafka.consumer. sensitive=false synonyms={}\n"
    )

    assert ClientMetricsManager._parse_subscriptions(raw) == [
        ClientMetricsSubscription(metric_name="org.apache.kafka.producer.", interval_ms=5000),
        ClientMetricsSubscription(metric_name="org.apache.kafka.consumer.", interval_ms=5000),
    ]


def test_parse_subscriptions_wildcard_metrics():
    """An empty `metrics` config subscribes to all client metrics."""
    raw = (
        "Dynamic configs for client-metric everything are:\n"
        "  interval.ms=300000 sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:interval.ms=300000}\n"
        "  metrics= sensitive=false synonyms={DYNAMIC_CLIENT_METRICS_CONFIG:metrics=}\n"
    )

    assert ClientMetricsManager._parse_subscriptions(raw) == [
        ClientMetricsSubscription(metric_name="", interval_ms=300000)
    ]


def test_parse_subscriptions_skips_resource_without_interval():
    raw = (
        "Dynamic configs for client-metric broken are:\n"
        "  metrics=org.apache.kafka.producer. sensitive=false synonyms={}\n"
    )

    assert ClientMetricsManager._parse_subscriptions(raw) == []


def test_current_subscriptions(manager, fake_workload):
    fake_workload.run_bin_command.return_value = DESCRIBE_OUTPUT

    assert len(manager.current_subscriptions) == 2

    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "configs"
    args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert f"--bootstrap-server {BOOTSTRAP_SERVER}" in args
    assert f"--command-config {fake_workload.paths.client_properties}" in args
    assert "--entity-type client-metrics" in args
    assert "--describe" in args


def test_add_subscription(manager, fake_workload):
    manager.add_subscription(metric_name="org.apache.kafka.producer.", interval=1000)

    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "configs"
    args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert "--entity-type client-metrics" in args
    assert "--entity-name org.apache.kafka.producer." in args
    assert "--alter" in args
    assert "--add-config interval.ms=1000,metrics=org.apache.kafka.producer." in args


def test_remove_subscription(manager, fake_workload):
    manager.remove_subscription(metric_name="org.apache.kafka.producer.")

    assert fake_workload.run_bin_command.call_args.kwargs["bin_keyword"] == "configs"
    args = " ".join(fake_workload.run_bin_command.call_args.kwargs["bin_args"])
    assert "--entity-type client-metrics" in args
    assert "--entity-name org.apache.kafka.producer." in args
    assert "--alter" in args
    assert "--delete-config interval.ms,metrics" in args
