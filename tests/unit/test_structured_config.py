#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import Iterable

import pytest
import yaml
from ops.testing import Container, Context, State
from pydantic import ValidationError

from charm import KafkaCharm
from core.structured_config import CharmConfig
from literals import (
    CONTAINER,
    SUBSTRATE,
)

pytestmark = [pytest.mark.broker, pytest.mark.balancer]


logger = logging.getLogger(__name__)


CONFIG = yaml.safe_load(Path("./config.yaml").read_text())
ACTIONS = yaml.safe_load(Path("./actions.yaml").read_text())
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture()
def base_state():
    if SUBSTRATE == "k8s":
        state = State(leader=True, containers=[Container(name=CONTAINER, can_connect=True)])

    else:
        state = State(leader=True)

    return state


@pytest.fixture()
def ctx() -> Context:
    ctx = Context(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS, unit_id=0)
    return ctx


def check_valid_values(field: str, accepted_values: Iterable) -> None:
    """Check the correctness of the passed values for a field."""
    flat_config_options = {
        option_name: mapping.get("default") for option_name, mapping in CONFIG["options"].items()
    }
    for value in accepted_values:
        CharmConfig(**{**flat_config_options, **{field: value}})


def check_invalid_values(field: str, erroneus_values: Iterable) -> None:
    """Check the incorrectness of the passed values for a field."""
    flat_config_options = {
        option_name: mapping.get("default") for option_name, mapping in CONFIG["options"].items()
    }
    for value in erroneus_values:
        with pytest.raises(ValidationError) as excinfo:
            CharmConfig(**{**flat_config_options, **{field: value}})
        assert field in excinfo.value.errors()[0]["loc"]


def test_config_parsing_parameters_integer_values() -> None:
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
        check_invalid_values(field, erroneus_values)
        check_valid_values(field, valid_values)


def test_product_related_values() -> None:
    """Test specific parameters for each field."""
    # log_message_timestamp_type field
    erroneus_values = ["test-value", "CreateTimes", "foo", "bar"]

    check_invalid_values("log_message_timestamp_type", erroneus_values)
    accepted_values = ["CreateTime", "LogAppendTime"]
    check_valid_values("log_message_timestamp_type", accepted_values)

    # log_cleanup_policy field
    check_invalid_values("log_cleanup_policy", erroneus_values)
    accepted_values = ["compact", "delete"]
    check_valid_values("log_cleanup_policy", accepted_values)

    # compression_type field
    check_invalid_values("compression_type", erroneus_values)
    accepted_values = ["gzip", "snappy", "lz4", "zstd", "uncompressed", "producer"]
    check_valid_values("compression_type", accepted_values)


def test_values_gt_zero() -> None:
    """Check fields greater than zero."""
    gt_zero_fields = ["log_flush_interval_messages", "log_flush_interval_ms"]
    erroneus_values = map(str, [0, -2147483649, -34])
    valid_values = map(str, [42, 1000, 1, 9223372036854775807])
    for field in gt_zero_fields:
        check_invalid_values(field, erroneus_values)
        check_valid_values(field, valid_values)


def test_values_gteq_zero() -> None:
    """Check fields greater or equal than zero."""
    gteq_zero_fields = [
        "replication_quota_window_num",
        "log_segment_bytes",
        "message_max_bytes",
    ]
    erroneus_values = [-2147483649, -34]
    valid_values = [42, 1000, 1, 0]
    for field in gteq_zero_fields:
        check_invalid_values(field, erroneus_values)
        check_valid_values(field, valid_values)


def test_values_in_specific_intervals() -> None:
    """Check fields on predefined intervals."""
    # "log_cleaner_delete_retention_ms"
    erroneus_values = map(str, [-1, 0, 1000 * 60 * 60 * 24 * 90 + 1])
    valid_values = map(str, [42, 1000, 10000, 1, 1000 * 60 * 60 * 24 * 90])
    check_invalid_values("log_cleaner_delete_retention_ms", erroneus_values)
    check_valid_values("log_cleaner_delete_retention_ms", valid_values)

    # "log_cleaner_min_compaction_lag_ms"
    erroneus_values = map(str, [-1, 1000 * 60 * 60 * 24 * 7 + 1])
    valid_values = map(str, [42, 1000, 10000, 1, 1000 * 60 * 60 * 24 * 7])
    check_invalid_values("log_cleaner_min_compaction_lag_ms", erroneus_values)
    check_valid_values("log_cleaner_min_compaction_lag_ms", valid_values)

    partititions_fields = [
        "transaction_state_log_num_partitions",
        "offsets_topic_num_partitions",
    ]
    erroneus_values = [10001, -1]
    valid_values = [42, 1000, 10000, 1]
    for field in partititions_fields:
        check_invalid_values(field, erroneus_values)
        check_valid_values(field, valid_values)


def test_config_parsing_parameters_long_values() -> None:
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
        check_invalid_values(field, erroneus_values)
        check_valid_values(field, valid_values)


def test_incorrect_roles():
    erroneus_values = ["", "something_else" "broker, something_else" "broker,balancer,"]
    valid_values = ["broker", "balancer", "balancer,broker", "broker, balancer "]
    check_invalid_values("roles", erroneus_values)
    check_valid_values("roles", valid_values)


def test_incorrect_extra_listeners():
    erroneus_values = [
        "missing.port",
        "low.port:15000",
        "high.port:60000",
        "non.unique:30000,other.non.unique:30000",
        "close.port:30000,other.close.port:30001",
    ]
    check_invalid_values("extra_listeners", erroneus_values)
