#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the Kafka charm."""
import math
from typing import Optional

from charms.data_platform_libs.v0.data_models import BaseConfigModel
from pydantic import validator


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    compression_type: str
    log_flush_interval_messages: int  # int  # long
    log_flush_interval_ms: Optional[int]  # long
    log_flush_offset_checkpoint_interval_ms: int
    log_retention_bytes: int  # long
    log_retention_ms: int  # long
    log_segment_bytes: int
    message_max_bytes: int
    offsets_topic_num_partitions: int
    transaction_state_log_num_partitions: int
    unclean_leader_election_enable: bool
    log_cleaner_delete_retention_ms: int  # long
    log_cleaner_min_compaction_lag_ms: int  # long
    log_cleanup_policy: str
    log_message_timestamp_type: str
    ssl_cipher_suites: Optional[str]
    replication_quota_window_num: int
    zookeeper_ssl_cipher_suites: Optional[str]

    @validator("*", pre=True)
    @classmethod
    def blank_string(cls, value):
        """Check for empty strings."""
        if value == "":
            return None
        return value

    @validator("log_message_timestamp_type")
    @classmethod
    def log_message_timestamp_type_validator(cls, value: str) -> Optional[str]:
        """Check validity of `log_message_timestamp_type` field."""
        accepted_values = ["CreateTime", "LogAppendTime"]
        if value not in accepted_values:
            raise ValueError(f"Value out of the accepted values: {accepted_values}")
        return value

    @validator("log_cleanup_policy")
    @classmethod
    def log_cleanup_policy_validator(cls, value: str) -> Optional[str]:
        """Check validity of `log_cleanup_policy` field."""
        accepted_values = ["compact", "delete"]
        if value not in accepted_values:
            raise ValueError(f"Value out of the accepted values: {accepted_values}")
        return value

    @validator("log_cleaner_min_compaction_lag_ms")
    @classmethod
    def log_cleaner_min_compaction_lag_ms_validator(cls, value: str) -> Optional[int]:
        """Check validity of `log_cleaner_min_compaction_lag_ms` field."""
        int_value = int(value)
        if int_value >= 0 and int_value <= 1000 * 60 * 60 * 24 * 7:
            return int_value
        raise ValueError("Value of of range.")

    @validator("log_cleaner_delete_retention_ms")
    @classmethod
    def log_cleaner_delete_retention_ms_validator(cls, value: str) -> Optional[int]:
        """Check validity of `log_cleaner_delete_retention_ms` field."""
        int_value = int(value)
        if int_value > 0 and int_value <= 1000 * 60 * 60 * 24 * 90:
            return int_value
        raise ValueError("Value of of range.")

    @validator("transaction_state_log_num_partitions", "offsets_topic_num_partitions")
    @classmethod
    def between_zero_and_10k(cls, value: int) -> Optional[int]:
        """Check that the integer value is between zero and 10000."""
        if value >= 0 and value <= 10000:
            return value
        raise ValueError("Value below zero or greater than 10000.")

    @validator("log_retention_bytes", "log_retention_ms")
    @classmethod
    def greater_than_minus_one(cls, value: str) -> Optional[int]:
        """Check value greater than -1."""
        int_value = int(value)
        if int_value < -1:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return int_value

    @validator("log_flush_interval_messages")
    @classmethod
    def greater_than_one(cls, value: str) -> Optional[int]:
        """Check value greater than one."""
        int_value = int(value)
        if int_value < 1:
            raise ValueError("Value below 1. Accepted value are greater or equal than 1.")
        return int_value

    @validator("log_flush_interval_ms")
    @classmethod
    def flush_interval(cls, value: int) -> Optional[int]:
        # 1-(1000*60*60)
        """Check value between 1 and than 1000*60*60."""
        if value > 0 and value <= 1000 * 60 * 60:
            return value
        raise ValueError(f"Value out of range [1 - {1000*60*60}]")

    @validator("replication_quota_window_num", "log_segment_bytes", "message_max_bytes")
    @classmethod
    def greater_than_zero(cls, value: int) -> Optional[int]:
        """Check value greater than zero."""
        if value < 0:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return value

    @validator("compression_type")
    @classmethod
    def value_compression_type(cls, value: str) -> Optional[str]:
        """Check validity of `compression_type` field."""
        accepted_values = ["gzip", "snappy", "lz4", "zstd" "uncompressed", "producer"]
        if value not in accepted_values:
            raise ValueError(f"Value out of the accepted values: {accepted_values}")
        return value

    @validator(
        "log_flush_offset_checkpoint_interval_ms",
        "log_segment_bytes",
        "message_max_bytes",
        "offsets_topic_num_partitions",
        "transaction_state_log_num_partitions",
        "replication_quota_window_num",
    )
    @classmethod
    def integer_value(cls, value: int) -> Optional[int]:
        """Check that the value is an integer (-2147483648,2147483647)."""
        if value >= -2147483648 and value <= 2147483647:
            return value
        raise ValueError("Value is not an integer")

    @validator(
        "log_flush_interval_messages",
        "log_flush_interval_ms",
        "log_retention_bytes",
        "log_retention_ms",
        "log_cleaner_delete_retention_ms",
        "log_cleaner_min_compaction_lag_ms",
    )
    @classmethod
    def long_value(cls, value: str) -> Optional[int]:
        """Check that the value is a long (-2^63 , 2^63 -1)."""
        int_value = int(value)
        if int_value >= -math.pow(2, 63) and int_value <= math.pow(2, 63) - 1:
            return int_value
        raise ValueError("Value is not an integer")
