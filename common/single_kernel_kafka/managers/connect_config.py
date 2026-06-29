#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka Connect configuration."""

import inspect
import logging
import os
from typing import cast

from ..core.connect_models import ConnectContext
from ..core.literals import (
    JMX_EXPORTER_PORT,
    ConnectLiterals,
)
from ..core.structured_config import ConnectCharmConfig
from ..core.workload import WorkloadBase

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
offset.flush.interval.ms=10000
heartbeat.interval.ms=3000
rebalance.timeout.ms=60000
session.timeout.ms=10000
ssl.enabled.protocols=TLSv1.3
ssl.protocol=TLSv1.3
worker.sync.timeout.ms=3000
worker.unsync.backoff.ms=300000
key.converter.schemas.enable=false
value.converter.schemas.enable=false
"""

PROPERTIES_BLACKLIST = [
    "system_users",
    "log_level",
    "profile",
    "rest_port",
]


CharmConfigType = str | int | bool


class ConfigManager:
    """Manager for handling Kafka Connect configuration."""

    config: ConnectCharmConfig
    workload: WorkloadBase
    context: ConnectContext

    VALUE_TRANSLATOR: dict[str, dict[CharmConfigType, str]] = {
        "exactly_once_source_support": {False: "disabled", True: "enabled"},
    }

    def __init__(
        self,
        context: ConnectContext,
        workload: WorkloadBase,
        config: ConnectCharmConfig,
        current_version: str = "",
    ):
        self.context = context
        self.workload = workload
        self.config = config
        self.current_version = current_version

    def _add_topic(
        self, mode: str, topic_name: ConnectLiterals.InternalTopics, replication_factor: int = -1
    ) -> list[str]:
        """Returns a list of key=value configuration entries for a given internal topic."""
        return [
            f"{mode}.storage.topic={topic_name}",
            f"{mode}.storage.replication.factor={replication_factor}",
        ]

    def _add_client(
        self, mode: ConnectLiterals.ClientModes, username: str, password: str
    ) -> list[str]:
        """Returns a list of key=value configuration entries for a given kafka client."""
        prefix_ = "" if mode == "worker" else f"{mode}."

        return [
            f"{prefix_}sasl.mechanism={self.context.kafka_client.security_mechanism}",
            f"{prefix_}security.protocol={self.context.kafka_client.security_protocol}",
            f'{prefix_}sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
        ]

    def translate_config(self, key: str, value: str) -> str:
        """Format `key: value` from charm config into appropriaate Kafka Connect `key=value` properties.

        Returns:
            String with Kafka configuration `key=value` to be placed in the connect properties file.
        """
        translated_value = self.VALUE_TRANSLATOR.get(key, {}).get(value, value)
        translated_key = key.replace("_", ".") if key not in PROPERTIES_BLACKLIST else f"# {key}"
        return f"{translated_key}={translated_value}"

    def save_jaas_config(self) -> None:
        """Writes JAAS configuration to `JAAS_PATH`."""
        if not self.jaas_config:
            return

        self.workload.write(content=self.jaas_config + "\n", path=self.workload.connect_paths.jaas)

    def save_properties(self) -> None:
        """Writes all Kafka Connect config properties to the `connect-distributed.properties` path."""
        self.workload.write(
            content="\n".join(self.properties) + "\n",
            path=self.workload.connect_paths.worker_properties,
        )

    def configure(self) -> None:
        """Make all steps necessary to start the Connect service, including setting env vars, JAAS config and service config files."""
        self.workload.set_environment(env_vars=[self.kafka_opts, self.log_level_opts])
        self.save_jaas_config()
        self.save_properties()

    @property
    def topic_properties(self) -> list[str]:
        """Returns the list of configuration for all internal topics."""
        properties = []
        for mode, topic_name in ConnectLiterals.TOPICS.items():
            properties.extend(
                self._add_topic(
                    mode,
                    topic_name=cast(ConnectLiterals.InternalTopics, topic_name),
                    replication_factor=ConnectLiterals.REPLICATION_FACTOR,
                )
            )
        return properties

    @property
    def jaas_config(self) -> str:
        """Returns necessary JAAS config for authentication."""
        return inspect.cleandoc(f"""
            KafkaConnect {{
                org.apache.kafka.connect.rest.basic.auth.extension.PropertyFileLoginModule required
                file="{self.workload.connect_paths.passwords}";
            }};
            """)

    @property
    def jmx_opts(self) -> list[str]:
        """The JMX options for configuring the prometheus exporter."""
        if not os.path.exists(self.workload.connect_paths.jmx_prometheus_config):
            return []

        return [
            f"-javaagent:{self.workload.connect_paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.workload.connect_paths.jmx_prometheus_config}",
        ]

    @property
    def kafka_opts(self) -> str:
        """Returns all necessary options for KAFKA_OPTS env var."""
        opts = [
            f"-Djava.security.auth.login.config={self.workload.connect_paths.jaas}",
            *self.jmx_opts,
        ]

        return f"KAFKA_OPTS='{' '.join(opts)}'"

    @property
    def log_level_opts(self) -> str:
        """Returns the log4j options for configuring the connect service logging."""
        # Remapping to WARN that is generally used in Java applications based on log4j and logback.
        log_level = "WARN" if self.config.log_level == "WARNING" else self.config.log_level

        opts = [
            f"-Dlog4j.configuration=file:{self.workload.connect_paths.log4j_properties} -Dcharmed.kafka.log.level={log_level}"
        ]

        return f"KAFKA_LOG4J_OPTS='{' '.join(opts)}'"

    @property
    def client_auth_properties(self) -> list[str]:
        """Returns the list of authentication properties for all client modes."""
        username = self.context.kafka_client.username
        password = self.context.kafka_client.password

        properties = []

        for mode in ("worker", "consumer", "producer"):
            properties.extend(self._add_client(mode=mode, username=username, password=password))

        return properties

    @property
    def rest_auth_properties(self) -> list[str]:
        """Returns authentication config properties on the REST API endpoint."""
        return [f"rest.extension.classes={ConnectLiterals.DEFAULT_AUTH_CLASS}"]

    @property
    def client_tls_properties(self) -> list[str]:
        """Returns the TLS properties for client if TLS is enabled."""
        if not self.context.kafka_client.tls_enabled:
            return []

        return [
            f"ssl.truststore.location={self.workload.connect_paths.truststore}",
            f"ssl.truststore.password={self.context.worker_unit.tls.truststore_password}",
        ]

    @property
    def rest_listener_properties(self) -> list[str]:
        """Returns Listener properties for the REST API endpoint."""
        return [
            f"listeners={self.context.rest_protocol}://{self.context.worker_unit.internal_address}:{self.context.rest_port}",
            f"rest.advertised.listener={self.context.rest_protocol}",
            f"rest.advertised.host.name={self.context.worker_unit.internal_address}",
            f"rest.advertised.host.port={self.context.rest_port}",
        ]

    @property
    def rest_tls_properties(self) -> list[str]:
        """Returns TLS properties for the REST API endpoint."""
        if not self.context.peer_workers.tls_enabled:
            return []

        return [
            "listeners.https.ssl.client.authentication=requested",
            f"listeners.https.ssl.truststore.location={self.workload.connect_paths.truststore}",
            f"listeners.https.ssl.truststore.password={self.context.worker_unit.tls.truststore_password}",
            f"listeners.https.ssl.keystore.location={self.workload.connect_paths.keystore}",
            f"listeners.https.ssl.keystore.password={self.context.worker_unit.tls.keystore_password}",
            "listeners.https.ssl.endpoint.identification.algorithm=HTTPS",
            # Workaround KAFKA-20572 issue
            "listeners.https.ssl.cipher.suites=TLS_AES_256_GCM_SHA384,TLS_CHACHA20_POLY1305_SHA256,TLS_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
        ]

    @property
    def charm_config_properties(self) -> list[str]:
        """Returns a list of properties populated from charm config."""
        return [
            self.translate_config(conf_key, value)
            for conf_key, value in self.config.dict().items()
            if value is not None
        ]

    @property
    def properties(self) -> list[str]:
        """Returns all properties necessary for starting Kafka Connect service."""
        properties = (
            [
                f"bootstrap.servers={self.context.kafka_client.bootstrap_servers}",
                f"group.id={ConnectLiterals.GROUP_ID}",
                f"plugin.path={self.workload.connect_paths.plugins}",
            ]
            + DEFAULT_CONFIG_OPTIONS.split("\n")
            + self.rest_listener_properties
            + self.rest_tls_properties
            + self.rest_auth_properties
            + self.client_auth_properties
            + self.client_tls_properties
            + self.topic_properties
            + self.charm_config_properties
        )

        return properties
