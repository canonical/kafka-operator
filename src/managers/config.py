#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import json
import logging
from typing import cast

from core.cluster import ClusterState
from core.structured_config import CharmConfig, LogLevel
from core.workload import WorkloadBase
from literals import (
    ADMIN_USER,
    INTER_BROKER_USER,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    SECURITY_PROTOCOL_PORTS,
    AuthMechanism,
    Scope,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
allow.everyone.if.no.acl.found=false
auto.create.topics.enable=false
metric.reporters=com.linkedin.kafka.cruisecontrol.metricsreporter.CruiseControlMetricsReporter
"""

CRUISE_CONTROL_CONFIG_OPTIONS = """
"""

SERVER_PROPERTIES_BLACKLIST = ["profile", "log_level", "certificate_extra_sans"]


class Listener:
    """Definition of a listener.

    Args:
        host: string with the host that will be announced
        protocol: auth protocol to be used
        scope: scope of the listener, CLIENT or INTERNAL
    """

    def __init__(self, host: str, protocol: AuthMechanism, scope: Scope):
        self.protocol: AuthMechanism = protocol
        self.host = host
        self.scope = scope

    @property
    def scope(self) -> Scope:
        """Internal scope validator."""
        return self._scope

    @scope.setter
    def scope(self, value):
        """Internal scope validator."""
        if value not in ["CLIENT", "INTERNAL"]:
            raise ValueError("Only CLIENT and INTERNAL scopes are accepted")

        self._scope = value

    @property
    def port(self) -> int:
        """Port associated with the protocol/scope.

        Defaults to internal port.

        Returns:
            Integer of port number
        """
        if self.scope == "CLIENT":
            return SECURITY_PROTOCOL_PORTS[self.protocol].client

        return SECURITY_PROTOCOL_PORTS[self.protocol].internal

    @property
    def name(self) -> str:
        """Name of the listener."""
        return f"{self.scope}_{self.protocol}"

    @property
    def protocol_map(self) -> str:
        """Return `name:protocol`."""
        return f"{self.name}:{self.protocol}"

    @property
    def listener(self) -> str:
        """Return `name://:port`."""
        return f"{self.name}://:{self.port}"

    @property
    def advertised_listener(self) -> str:
        """Return `name://host:port`."""
        return f"{self.name}://{self.host}:{self.port}"


class KafkaConfigManager:
    """Manager for handling Kafka configuration."""

    def __init__(
        self,
        state: ClusterState,
        workload: WorkloadBase,
        config: CharmConfig,
        current_version: str,
    ):
        self.state = state
        self.workload = workload
        self.config = config
        self.current_version = current_version

    @property
    def log_level(self) -> str:
        """Return the Java-compliant logging level set by the user.

        Returns:
            String with these possible values: DEBUG, INFO, WARN, ERROR
        """
        # Remapping to WARN that is generally used in Java applications based on log4j and logback.
        if self.config.log_level == LogLevel.WARNING.value:
            return "WARN"
        return self.config.log_level

    @property
    def jmx_opts(self) -> str:
        """The JMX options for configuring the prometheus exporter.

        Returns:
            String of JMX options
        """
        opts = [
            "-Dcom.sun.management.jmxremote",
            f"-javaagent:{self.workload.paths.jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.workload.paths.jmx_prometheus_config}",
        ]

        return f"KAFKA_JMX_OPTS='{' '.join(opts)}'"

    @property
    def jvm_performance_opts(self) -> str:
        """The JVM config options for tuning performance settings.

        Returns:
            String of JVM performance options
        """
        opts = [
            "-XX:MetaspaceSize=96m",
            "-XX:+UseG1GC",
            "-XX:MaxGCPauseMillis=20",
            "-XX:InitiatingHeapOccupancyPercent=35",
            "-XX:G1HeapRegionSize=16M",
            "-XX:MinMetaspaceFreeRatio=50",
            "-XX:MaxMetaspaceFreeRatio=80",
        ]

        return f"KAFKA_JVM_PERFORMANCE_OPTS='{' '.join(opts)}'"

    @property
    def heap_opts(self) -> str:
        """The JVM config options for setting heap limits.

        Returns:
            String of JVM heap memory options
        """
        target_memory = JVM_MEM_MIN_GB if self.config.profile == "testing" else JVM_MEM_MAX_GB
        opts = [
            f"-Xms{target_memory}G",
            f"-Xmx{target_memory}G",
        ]

        return f"KAFKA_HEAP_OPTS='{' '.join(opts)}'"

    @property
    def kafka_opts(self) -> str:
        """Extra Java config options.

        Returns:
            String of Java config options
        """
        opts = [
            f"-Djava.security.auth.login.config={self.workload.paths.zk_jaas}",
            f"-Dcharmed.kafka.log.level={self.log_level}",
        ]

        return f"KAFKA_OPTS='{' '.join(opts)}'"

    @property
    def default_replication_properties(self) -> list[str]:
        """Builds replication-related properties based on the expected app size.

        Returns:
            List of properties to be set
        """
        replication_factor = min([3, self.state.planned_units])
        min_isr = max([1, replication_factor - 1])

        return [
            f"default.replication.factor={replication_factor}",
            f"num.partitions={replication_factor}",
            f"transaction.state.log.replication.factor={replication_factor}",
            f"offsets.topic.replication.factor={replication_factor}",
            f"min.insync.replicas={min_isr}",
            f"transaction.state.log.min.isr={min_isr}",
        ]

    @property
    def auth_properties(self) -> list[str]:
        """Builds properties necessary for inter-broker authorization through ZooKeeper.

        Returns:
            List of properties to be set
        """
        return [
            f"broker.id={self.state.broker.unit_id}",
            f"zookeeper.connect={self.state.zookeeper.connect}",
        ]

    @property
    def zookeeper_tls_properties(self) -> list[str]:
        """Builds the properties necessary for SSL connections to ZooKeeper.

        Returns:
            List of properties to be set
        """
        return [
            "zookeeper.ssl.client.enable=true",
            f"zookeeper.ssl.truststore.location={self.workload.paths.truststore}",
            f"zookeeper.ssl.truststore.password={self.state.broker.truststore_password}",
            "zookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty",
        ]

    @property
    def tls_properties(self) -> list[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set
        """
        mtls = "required" if self.state.cluster.mtls_enabled else "none"
        return [
            f"ssl.truststore.location={self.workload.paths.truststore}",
            f"ssl.truststore.password={self.state.broker.truststore_password}",
            f"ssl.keystore.location={self.workload.paths.keystore}",
            f"ssl.keystore.password={self.state.broker.keystore_password}",
            f"ssl.client.auth={mtls}",
        ]

    @property
    def scram_properties(self) -> list[str]:
        """Builds the properties for each scram listener.

        Returns:
            list of scram properties to be set
        """
        username = INTER_BROKER_USER
        password = self.state.cluster.internal_user_credentials.get(INTER_BROKER_USER, "")

        scram_properties = [
            f'listener.name.{self.internal_listener.name.lower()}.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";'
        ]
        client_scram = [
            auth.name for auth in self.client_listeners if auth.protocol.startswith("SASL_")
        ]
        for name in client_scram:
            scram_properties.append(
                f'listener.name.{name.lower()}.scram-sha-512.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";'
            )

        return scram_properties

    @property
    def security_protocol(self) -> AuthMechanism:
        """Infers current charm security.protocol based on current relations."""
        # FIXME: When we have multiple auth_mechanims/listeners, remove this method
        return (
            "SASL_SSL"
            if (self.state.cluster.tls_enabled and self.state.broker.certificate)
            else "SASL_PLAINTEXT"
        )

    @property
    def auth_mechanisms(self) -> list[AuthMechanism]:
        """Return a list of enabled auth mechanisms."""
        # TODO: At the moment only one mechanism for extra listeners. Will need to be
        # extended with more depending on configuration settings.
        protocol = [self.security_protocol]
        if self.state.cluster.mtls_enabled:
            protocol += ["SSL"]

        return cast(list[AuthMechanism], protocol)

    @property
    def internal_listener(self) -> Listener:
        """Return the internal listener."""
        protocol = self.security_protocol
        return Listener(host=self.state.broker.host, protocol=protocol, scope="INTERNAL")

    @property
    def client_listeners(self) -> list[Listener]:
        """Return a list of extra listeners."""
        # if there is a relation with kafka then add extra listener
        if not self.state.client_relations:
            return []

        return [
            Listener(host=self.state.broker.host, protocol=auth, scope="CLIENT")
            for auth in self.auth_mechanisms
        ]

    @property
    def all_listeners(self) -> list[Listener]:
        """Return a list with all expected listeners."""
        return [self.internal_listener] + self.client_listeners

    @property
    def inter_broker_protocol_version(self) -> str:
        """Creates the protocol version from the kafka version.

        Returns:
            String with the `major.minor` version
        """
        # Remove patch number from full vervion.
        major_minor = self.current_version.split(".", maxsplit=2)
        return ".".join(major_minor[:2])

    @property
    def rack_properties(self) -> list[str]:
        """Builds all properties related to rack awareness configuration.

        Returns:
            List of properties to be set
        """
        # TODO: not sure if we should make this an instance attribute like the other paths
        rack_path = f"{self.workload.paths.conf_path}/rack.properties"
        return self.workload.read(rack_path) or []

    @property
    def client_properties(self) -> list[str]:
        """Builds all properties necessary for running an admin Kafka client.

        This includes SASL/SCRAM auth and security mechanisms.

        Returns:
            List of properties to be set
        """
        username = ADMIN_USER
        password = self.state.cluster.internal_user_credentials.get(ADMIN_USER, "")

        client_properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
            "sasl.mechanism=SCRAM-SHA-512",
            f"security.protocol={self.security_protocol}",
            # FIXME: security.protocol will need changing once multiple listener auth schemes
            f"bootstrap.servers={','.join(self.state.bootstrap_server)}",
        ]

        if self.state.cluster.tls_enabled and self.state.broker.certificate:
            client_properties += self.tls_properties

        return client_properties

    @property
    def broker_capacities(self) -> str:
        """Builds the capacityJBOD JSON configuration for broker storages.

        Returns:
            String of JSON to be set
        """
        broker_capacities = []
        for broker in self.state.brokers:
            broker_capacities.append(
                {
                    "brokerId": str(broker.unit_id),
                    "capacity": {
                        "DISK": broker.storages,
                        "CPU": {"num.cores": broker.cores},
                        "NW_IN": self.config.network_bandwidth,
                        "NW_OUT": self.config.network_bandwidth,
                    },
                    "doc": broker.component.name,
                }
            )

        return json.dumps({"brokerCapacities": broker_capacities}, indent=4)

    @property
    def cruise_control_properties(self) -> list[str]:
        """Builds all properties necessary for starting Cruise Control service.

        Returns:
            List of properties to be set
        """
        properties = [
            f"bootstrap.servers={','.join(self.state.bootstrap_server)}",
            f"capacity.config.file={self.workload.paths.capacity_jbod_json}",
            f"zookeeper.connect={self.state.zookeeper.connect}",
        ] + CRUISE_CONTROL_CONFIG_OPTIONS.split("\n")

        return properties

    @property
    def server_properties(self) -> list[str]:
        """Builds all properties necessary for starting Kafka service.

        This includes charm config, replication, SASL/SCRAM auth and default properties.

        Returns:
            List of properties to be set

        Raises:
            KeyError if inter-broker username and password not set to relation data
        """
        protocol_map = [listener.protocol_map for listener in self.all_listeners]
        listeners_repr = [listener.listener for listener in self.all_listeners]
        advertised_listeners = [listener.advertised_listener for listener in self.all_listeners]

        properties = (
            [
                f"super.users={self.state.super_users}",
                f"log.dirs={self.state.log_dirs}",
                f"listener.security.protocol.map={','.join(protocol_map)}",
                f"listeners={','.join(listeners_repr)}",
                f"advertised.listeners={','.join(advertised_listeners)}",
                f"inter.broker.listener.name={self.internal_listener.name}",
                f"inter.broker.protocol.version={self.inter_broker_protocol_version}",
            ]
            + self.config_properties
            + self.scram_properties
            + self.default_replication_properties
            + self.auth_properties
            + self.rack_properties
            + DEFAULT_CONFIG_OPTIONS.split("\n")
        )

        if self.state.cluster.tls_enabled and self.state.broker.certificate:
            properties += self.tls_properties + self.zookeeper_tls_properties
            properties += [
                f"cruise.control.metrics.reporter.{prop}" for prop in self.tls_properties
            ]

        return properties

    @property
    def config_properties(self) -> list[str]:
        """Configure server properties from config."""
        return [
            f"{self._translate_config_key(conf_key)}={str(value)}"
            for conf_key, value in self.config.dict().items()
            if value is not None
        ]

    @property
    def zk_jaas_config(self) -> str:
        """Builds the JAAS config for Client authentication with ZooKeeper.

        Returns:
            String of JAAS config for ZooKeeper auth
        """
        return f"""
Client {{
    org.apache.zookeeper.server.auth.DigestLoginModule required
    username="{self.state.zookeeper.username}"
    password="{self.state.zookeeper.password}";
}};
        """

    @property
    def cruise_control_jaas_config(self) -> str:
        """Builds the JAAS config for KafkaClient authentication with Kafka.

        Returns:
            String of JAAS config for Kafka auth
        """
        return f"""
KafkaClient {{
    org.apache.kafka.common.security.scram.ScramLoginModule required
    username="{ADMIN_USER}"
    password="{self.state.cluster.internal_user_credentials.get(ADMIN_USER)}";
}};
        """

    def set_zk_jaas_config(self) -> None:
        """Writes the ZooKeeper JAAS config using ZooKeeper relation data."""
        # normally we would need to also write a JAAS specifically for CC to authenticate to ZooKeeper + Kafka
        # however the path is fixed to be inferred from where the snap squashfs is
        # however, it KAFKA_OPTS for -Djava.security.auth.login.config, so we can add both there
        self.workload.write(
            content="\n".join([self.zk_jaas_config, self.cruise_control_jaas_config]),
            path=self.workload.paths.zk_jaas,
        )

    def set_server_properties(self) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        self.workload.write(
            content="\n".join(self.server_properties), path=self.workload.paths.server_properties
        )

    def set_client_properties(self) -> None:
        """Writes all client config properties to the `client.properties` path."""
        self.workload.write(
            content="\n".join(self.client_properties), path=self.workload.paths.client_properties
        )

    def set_cruise_control_properties(self) -> None:
        """Writes all broker storage capacities to `capacityJBOD.json`."""
        self.workload.write(
            content="\n".join(self.cruise_control_properties),
            path=self.workload.paths.cruise_control_properties,
        )

    def set_broker_capacities(self) -> None:
        """Writes all broker storage capacities to `capacityJBOD.json`."""
        self.workload.write(
            content=self.broker_capacities, path=self.workload.paths.capacity_jbod_json
        )

    def set_environment(self) -> None:
        """Writes the env-vars needed for passing to charmed-kafka service."""
        updated_env_list = [
            self.kafka_opts,
            self.jmx_opts,
            self.jvm_performance_opts,
            self.heap_opts,
        ]

        def map_env(env: list[str]) -> dict[str, str]:
            map_env = {}
            for var in env:
                key = "".join(var.split("=", maxsplit=1)[0])
                value = "".join(var.split("=", maxsplit=1)[1:])
                if key:
                    # only check for keys, as we can have an empty value for a variable
                    map_env[key] = value
            return map_env

        raw_current_env = self.workload.read("/etc/environment")
        current_env = map_env(raw_current_env)

        updated_env = current_env | map_env(updated_env_list)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.workload.write(content=content, path="/etc/environment")

    @staticmethod
    def _translate_config_key(key: str):
        """Format config names into server properties, blacklisted property are commented out.

        Returns:
            String with Kafka configuration name to be placed in the server.properties file
        """
        return key.replace("_", ".") if key not in SERVER_PROPERTIES_BLACKLIST else f"# {key}"
