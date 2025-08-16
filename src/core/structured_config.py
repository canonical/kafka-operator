#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Structured configuration for the Kafka charm."""

import logging
import re
from enum import Enum
from typing import Literal

from charms.data_platform_libs.v0.data_models import BaseConfigModel
from pydantic import Field, validator

from literals import BALANCER, BROKER, CONTROLLER, SUBSTRATE
from managers.ssl_principal_mapper import SslPrincipalMapper

logger = logging.getLogger(__name__)


SECRET_REGEX = re.compile("secret:[a-z0-9]{20}")


class LogLevel(str, Enum):
    """Enum for the `log_level` field."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"


class CharmConfig(BaseConfigModel):
    """Manager for the structured configuration."""

    # Kafka configs
    compression_type: Literal["gzip", "snappy", "lz4", "zstd", "uncompressed", "producer"]
    log_flush_interval_messages: int  # int  # long
    log_flush_interval_ms: int | None  # long
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
    log_cleanup_policy: Literal["compact", "delete"]
    log_message_timestamp_type: Literal["CreateTime", "LogAppendTime"]
    ssl_cipher_suites: str | None
    ssl_principal_mapping_rules: str
    replication_quota_window_num: int
    # Charm configs
    roles: str
    profile: Literal["testing", "staging", "production"]
    certificate_extra_sans: list[str]
    extra_listeners: list[str]
    expose_external: str | None
    log_level: str
    network_bandwidth: int = Field(default=50000, validate_default=False, gt=0)
    cruisecontrol_balance_threshold: float = Field(default=1.1, validate_default=False, ge=1)
    cruisecontrol_capacity_threshold: float = Field(default=0.8, validate_default=False, le=1)
    system_users: str | None = None
    tls_private_key: str | None = None

    @validator("*", pre=True)
    @classmethod
    def blank_string(cls, value):
        """Check for empty strings."""
        if value == "":
            return None
        return value

    @validator("log_cleaner_min_compaction_lag_ms")
    @classmethod
    def log_cleaner_min_compaction_lag_ms_validator(cls, value: str) -> int | None:
        """Check validity of `log_cleaner_min_compaction_lag_ms` field."""
        int_value = int(value)
        if int_value >= 0 and int_value <= 1000 * 60 * 60 * 24 * 7:
            return int_value
        raise ValueError("Value out of range.")

    @validator("log_cleaner_delete_retention_ms")
    @classmethod
    def log_cleaner_delete_retention_ms_validator(cls, value: str) -> int | None:
        """Check validity of `log_cleaner_delete_retention_ms` field."""
        int_value = int(value)
        if int_value > 0 and int_value <= 1000 * 60 * 60 * 24 * 90:
            return int_value
        raise ValueError("Value out of range.")

    @validator("ssl_principal_mapping_rules")
    @classmethod
    def ssl_principal_mapping_rules_validator(cls, value: str) -> str | None:
        """Check that the list is formed by valid regex values."""
        rules = SslPrincipalMapper.split_rules(value)
        # parse_rules will raise ValueError if the rules are not valid
        SslPrincipalMapper.parse_rules(rules)
        return value

    @validator("transaction_state_log_num_partitions", "offsets_topic_num_partitions")
    @classmethod
    def between_zero_and_10k(cls, value: int) -> int | None:
        """Check that the integer value is between zero and 10000."""
        if value >= 0 and value <= 10000:
            return value
        raise ValueError("Value below zero or greater than 10000.")

    @validator("log_retention_bytes", "log_retention_ms")
    @classmethod
    def greater_than_minus_one(cls, value: str) -> int | None:
        """Check value greater than -1."""
        int_value = int(value)
        if int_value < -1:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return int_value

    @validator(
        "log_flush_interval_messages",
        "log_flush_interval_ms",
        "offsets_topic_num_partitions",
        "transaction_state_log_num_partitions",
        "replication_quota_window_num",
    )
    @classmethod
    def greater_than_one(cls, value: str) -> int | None:
        """Check value greater than one."""
        int_value = int(value)
        if int_value < 1:
            raise ValueError("Value below 1. Accepted value are greater or equal than 1.")
        return int_value

    @validator("log_segment_bytes")
    @classmethod
    def greater_than_1_mb(cls, value: int) -> int | None:
        """Check value greater than 1 MB."""
        if value < 1024 * 1024:
            raise ValueError("Value below 1 MB. Accepted value are greater or equal than 1 MB.")
        return value

    @validator("message_max_bytes")
    @classmethod
    def greater_than_zero(cls, value: int) -> int | None:
        """Check value greater than zero."""
        if value < 0:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
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
    def integer_value(cls, value: int) -> int | None:
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
    def long_value(cls, value: str) -> int | None:
        """Check that the value is a long (-2^63 , 2^63 -1)."""
        int_value = int(value)
        if int_value >= -9223372036854775807 and int_value <= 9223372036854775808:
            return int_value
        raise ValueError("Value is not a long")

    @validator("expose_external")
    @classmethod
    def expose_external_validator(cls, value: str) -> str | None:
        """Check expose_external config option is only used on Kubernetes charm."""
        if SUBSTRATE == "vm":
            return

        if value not in ["false", "nodeport"]:
            raise ValueError("Value not one of 'false' or 'nodeport'")

        if value == "false":
            return

        return value

    @validator("roles", pre=True)
    @classmethod
    def roles_values(cls, value: str) -> str:
        """Check roles values."""
        roles = set(map(str.strip, value.split(",")))

        if unknown_roles := roles - {BROKER.value, BALANCER.value, CONTROLLER.value}:
            raise ValueError("Unknown role(s):", unknown_roles)

        return ",".join(sorted(roles))  # this has to be a string as it goes in to properties

    @validator("certificate_extra_sans", pre=True)
    @classmethod
    def certificate_extra_sans_values(cls, value: str) -> list[str]:
        """Formats certificate_extra_sans values to a list."""
        return value.split(",") if value else []

    @validator("extra_listeners", pre=True)
    @classmethod
    def extra_listeners_port_values(cls, value: str) -> list[str]:
        """Check extra_listeners port values for each listener, and format values to a list."""
        if not value:
            return []

        listeners = value.split(",")

        ports = []
        for listener in listeners:
            if ":" not in listener:
                continue

            if not listener.split(":")[1].isdigit():
                raise ValueError("Value for listener does not contain a valid port.")

            port = int(listener.split(":")[1])
            if not 20000 < port < 50000:
                raise ValueError(
                    "Value for port out of accepted values. Accepted values for port are greater than 20000 and less than 50000"
                )

            ports.append(port)

        current_port = 0
        for port in ports:
            if not current_port - 100 < int(port) > current_port + 100:
                raise ValueError(
                    "Value for port is too close to other value for port. Accepted values must be at least 100 apart from each other"
                )

            current_port = int(port)

        if len(ports) != len(set(ports)):
            raise ValueError("Value for port is not unique for each listener.")

        return listeners

    @validator("system_users", "tls_private_key")
    @classmethod
    def secret_validator(cls, value: str) -> str:
        """Check validity of fields which should be a secret URI."""
        if not value:
            return ""

        if not SECRET_REGEX.match(value):
            raise ValueError(
                "Provided value for secret config is not a valid secret URI, "
                "accepted values are formatted like 'secret:cvnra0b1c2e3f4g5hi6j'"
            )

        return value
