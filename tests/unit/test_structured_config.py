#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from ops.testing import Harness

from charm import KafkaCharm
from literals import CHARM_KEY, CONTAINER, SUBSTRATE

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))

logger = logging.getLogger(__name__)


@pytest.fixture
def harness():
    harness = Harness(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS)

    if SUBSTRATE == "k8s":
        harness.set_can_connect(CONTAINER, True)

    harness.add_relation("restart", CHARM_KEY)
    harness.begin()
    return harness


def test_config_parsing_parameters_integer_values(harness) -> None:
    """Check that integer fields are parsed correctly."""
    integer_fields = [
        "log_flush_offset_checkpoint_interval_ms",
        "log_segment_bytes",
        "message_max_bytes",
        "offsets_topic_num_partitions",
        "transaction_state_log_num_partitions",
        "replication_quota_window_num",
    ]
    erroneus_values = [2147483648, -2147483649]
    valid_values = [42, 1000, 1]
    for field in integer_fields:
        check_invalid_values(harness, field, erroneus_values)
        check_valid_values(harness, field, valid_values)


def check_valid_values(_harness, field: str, accepted_values: list, is_long_field=False) -> None:
    """Check the correctness of the passed values for a field."""
    for value in accepted_values:
        _harness.update_config({field: value})
        assert _harness.charm.config[field] == value if not is_long_field else int(value)


def check_invalid_values(_harness, field: str, erroneus_values: list) -> None:
    """Check the incorrectness of the passed values for a field."""
    for value in erroneus_values:
        _harness.update_config({field: value})
        with pytest.raises(ValueError):
            _ = _harness.charm.config[field]


def test_product_related_values(harness) -> None:
    """Test specific parameters for each field."""
    # log_message_timestamp_type field
    erroneus_values = ["test-value", "CreateTimes", "foo", "bar"]

    check_invalid_values(harness, "log_message_timestamp_type", erroneus_values)
    accepted_values = ["CreateTime", "LogAppendTime"]
    check_valid_values(harness, "log_message_timestamp_type", accepted_values)

    # log_cleanup_policy field
    check_invalid_values(harness, "log_cleanup_policy", erroneus_values)
    accepted_values = ["compact", "delete"]
    check_valid_values(harness, "log_cleanup_policy", accepted_values)

    # compression_type field
    check_invalid_values(harness, "compression_type", erroneus_values)
    accepted_values = ["gzip", "snappy", "lz4", "zstd", "uncompressed", "producer"]
    check_valid_values(harness, "compression_type", accepted_values)


def test_values_gt_zero(harness) -> None:
    """Check fields greater than zero."""
    gt_zero_fields = ["log_flush_interval_messages", "log_flush_interval_ms"]
    erroneus_values = map(str, [0, -2147483649, -34])
    valid_values = map(str, [42, 1000, 1, 9223372036854775807])
    for field in gt_zero_fields:
        check_invalid_values(harness, field, erroneus_values)
        check_valid_values(harness, field, valid_values, is_long_field=True)


def test_values_gteq_zero(harness) -> None:
    """Check fields greater or equal than zero."""
    gteq_zero_fields = [
        "replication_quota_window_num",
        "log_segment_bytes",
        "message_max_bytes",
    ]
    erroneus_values = [-2147483649, -34]
    valid_values = [42, 1000, 1, 0]
    for field in gteq_zero_fields:
        check_invalid_values(harness, field, erroneus_values)
        check_valid_values(harness, field, valid_values)


def test_values_in_specific_intervals(harness) -> None:
    """Check fields on predefined intervals."""
    # "log_cleaner_delete_retention_ms"
    erroneus_values = map(str, [-1, 0, 1000 * 60 * 60 * 24 * 90 + 1])
    valid_values = map(str, [42, 1000, 10000, 1, 1000 * 60 * 60 * 24 * 90])
    check_invalid_values(harness, "log_cleaner_delete_retention_ms", erroneus_values)
    check_valid_values(
        harness, "log_cleaner_delete_retention_ms", valid_values, is_long_field=True
    )

    # "log_cleaner_min_compaction_lag_ms"
    erroneus_values = map(str, [-1, 1000 * 60 * 60 * 24 * 7 + 1])
    valid_values = map(str, [42, 1000, 10000, 1, 1000 * 60 * 60 * 24 * 7])
    check_invalid_values(harness, "log_cleaner_min_compaction_lag_ms", erroneus_values)
    check_valid_values(
        harness, "log_cleaner_min_compaction_lag_ms", valid_values, is_long_field=True
    )

    partititions_fields = [
        "transaction_state_log_num_partitions",
        "offsets_topic_num_partitions",
    ]
    erroneus_values = [10001, -1]
    valid_values = [42, 1000, 10000, 1]
    for field in partititions_fields:
        check_invalid_values(harness, field, erroneus_values)
        check_valid_values(harness, field, valid_values)


def test_config_parsing_parameters_long_values(harness) -> None:
    """Check long fields are parsed correctly."""
    long_fields = [
        "log_flush_interval_messages",
        "log_flush_interval_ms",
        "log_retention_bytes",
        "log_retention_ms",
        "log_cleaner_delete_retention_ms",
        "log_cleaner_min_compaction_lag_ms",
    ]
    erroneus_values = map(str, [-9223372036854775808, 9223372036854775809])
    valid_values = map(str, [42, 1000, 9223372036854775808])
    for field in long_fields:
        check_invalid_values(harness, field, erroneus_values)
        check_valid_values(harness, field, valid_values, is_long_field=True)
