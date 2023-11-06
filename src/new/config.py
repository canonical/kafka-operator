#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import logging
import os
from typing import List, cast
from typing import Optional

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
from new.core.models import ClusterRelation, ZookeeperConfig, KafkaClient, UpgradeRelation
from new.core.workload import CharmedKafkaPath
from new.core.models import KafkaConfig
from utils import map_env

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
sasl.enabled.mechanisms=SCRAM-SHA-512
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
allow.everyone.if.no.acl.found=false
auto.create.topics.enable=false
"""


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


class ServerConfig:
    """Manager for handling Kafka configuration."""

    def __init__(self,
                 charm_config: KafkaConfig,
                 kafka_paths: CharmedKafkaPath[str],
                 cluster: ClusterRelation,
                 upgrade: UpgradeRelation,
                 zookeeper: Optional[ZookeeperConfig],
                 kafka_clients: dict[int, KafkaClient]
                 ):
        self.charm_config = charm_config
        self.kafka_paths = kafka_paths
        self.cluster = cluster
        self.zookeeper = zookeeper
        self.upgrade = upgrade
        self.kafka_clients = kafka_clients

    @property
    def log4j_opts(self) -> str:
        """The Java config options for specifying log4j properties.

        Returns:
            String of Java config options
        """
        opts = [f"-Dlog4j.configuration=file:{self.kafka_paths.log4j_properties}"]

        return f"KAFKA_LOG4J_OPTS='{' '.join(opts)}'"

    @property
    def jmx_opts(self) -> str:
        """The JMX options for configuring the prometheus exporter.

        Returns:
            String of JMX options
        """
        opts = [
            "-Dcom.sun.management.jmxremote",
            f"-javaagent:{self.kafka_paths.jmx_prometheus_javaagent}"
            f"={JMX_EXPORTER_PORT}:{self.kafka_paths.jmx_prometheus_config}",
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
        target_memory = (
            JVM_MEM_MIN_GB if self.charm_config.profile == "testing" else JVM_MEM_MAX_GB
        )
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
            f"-Djava.security.auth.login.config={self.kafka_paths.zk_jaas}",
            "-Djavax.net.debug=ssl:handshake:verbose:session:keymanager:trustmanager",
        ]

        return f"KAFKA_OPTS='{' '.join(opts)}'"

    @property
    def bootstrap_server(self) -> List[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        # port = (
        #     SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
        #     if (self.cluster.tls.enabled and self.cluster.tls.certificate)
        #     else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        # )
        # return [f"{host.host}:{port}" for host in self.cluster.hosts]
        return self.cluster.bootstrap_servers

    @property
    def default_replication_properties(self) -> List[str]:
        """Builds replication-related properties based on the expected app size.

        Returns:
            List of properties to be set
        """
        replication_factor = min([3,
                                  self.charm_config.planned_units])  # How to infer this? Extra property or from peer_relation?
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
    def auth_properties(self) -> List[str]:
        """Builds properties necessary for inter-broker authorization through ZooKeeper.

        Returns:
            List of properties to be set
        """
        broker = self.cluster.unit
        return [
            f"broker.id={broker.unit}",
            f'zookeeper.connect={self.zookeeper.connect}',
        ]

    @property
    def zookeeper_tls_properties(self) -> List[str]:
        """Builds the properties necessary for SSL connections to ZooKeeper.

        Returns:
            List of properties to be set
        """
        return [
            "zookeeper.ssl.client.enable=true",
            f"zookeeper.ssl.truststore.location={self.kafka_paths.truststore}",
            f"zookeeper.ssl.truststore.password={self.cluster.tls.truststore_password}",
            "zookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty",
        ]

    @property
    def tls_properties(self) -> List[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set
        """
        mtls = "required" if self.cluster.tls.mtls_enabled else "none"
        return [
            f"ssl.truststore.location={self.kafka_paths.truststore}",
            f"ssl.truststore.password={self.cluster.tls.truststore_password}",
            f"ssl.keystore.location={self.kafka_paths.keystore}",
            f"ssl.keystore.password={self.cluster.tls.keystore_password}",
            f"ssl.client.auth={mtls}",
        ]

    @property
    def scram_properties(self) -> List[str]:
        """Builds the properties for each scram listener.

        Returns:
            list of scram properties to be set
        """
        username = INTER_BROKER_USER
        password = self.cluster.internal_user_credentials.get(INTER_BROKER_USER, "")

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
        return cast(AuthMechanism,
                    "SASL_SSL"
                    if (self.cluster.tls and self.cluster.tls.certificate)
                    else "SASL_PLAINTEXT"
                    )

    @property
    def auth_mechanisms(self) -> List[AuthMechanism]:
        """Return a list of enabled auth mechanisms."""
        # TODO: At the moment only one mechanism for extra listeners. Will need to be
        # extended with more depending on configuration settings.
        protocol = [self.security_protocol]
        if self.cluster.tls.mtls_enabled:
            protocol += ["SSL"]

        return cast(List[AuthMechanism], protocol)

    @property
    def internal_listener(self) -> Listener:
        """Return the internal listener."""
        protocol = self.security_protocol
        return Listener(host=self.cluster.unit.host, protocol=protocol, scope="INTERNAL")

    @property
    def client_listeners(self) -> List[Listener]:
        """Return a list of extra listeners."""
        # if there is a relation with kafka then add extra listener
        if not self.kafka_clients:
            return []

        return [
            Listener(host=self.cluster.unit.host, protocol=auth, scope="CLIENT")
            for auth in self.auth_mechanisms
        ]

    @property
    def all_listeners(self) -> List[Listener]:
        """Return a list with all expected listeners."""
        return [self.internal_listener] + self.client_listeners

    @property
    def super_users(self) -> str:
        """Generates all users with super/admin permissions for the cluster from relations.

        Formatting allows passing to the `super.users` property.

        Returns:
            Semicolon delimited string of current super users
        """
        super_users = list(*self.cluster.internal_user_credentials.keys()) + [
            client.username for client in self.kafka_clients.values()
        ]

        return ";".join(sorted([f"User:{user}" for user in super_users]))

    @property
    def log_dirs(self) -> str:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            String of log.dirs property value to be set
        """
        return ",".join(
            [os.fspath(storage.location) for storage in self.charm_config.storages["data"]]
        )

    @property
    def inter_broker_protocol_version(self) -> str:
        """Creates the protocol version from the kafka version.

        Returns:
            String with the `major.minor` version
        """
        # Remove patch number from full vervion.
        return self.upgrade.major_minor

    # @property
    # def rack_properties(self) -> List[str]:
    #     """Builds all properties related to rack awareness configuration.
    #
    #     Returns:
    #         List of properties to be set
    #     """
    #     # TODO: not sure if we should make this an instance attribute like the other paths
    #     rack_path = f"{self.charm.snap.CONF_PATH}/rack.properties"
    #     return safe_get_file(rack_path) or []

    @property
    def client_properties(self) -> List[str]:
        """Builds all properties necessary for running an admin Kafka client.

        This includes SASL/SCRAM auth and security mechanisms.

        Returns:
            List of properties to be set
        """
        username = ADMIN_USER
        password = self.cluster.internal_user_credentials.get(ADMIN_USER, "")

        client_properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
            "sasl.mechanism=SCRAM-SHA-512",
            f"security.protocol={self.security_protocol}",
            # FIXME: will need changing once multiple listener auth schemes
            f"bootstrap.servers={','.join(self.bootstrap_server)}",
        ]

        if self.cluster.tls.enabled and self.cluster.tls.certificate:
            client_properties += self.tls_properties

        return client_properties

    @property
    def server_properties(self) -> List[str]:
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
                    f"super.users={self.super_users}",
                    f"log.dirs={self.log_dirs}",
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
                # + self.rack_properties
                + DEFAULT_CONFIG_OPTIONS.split("\n")
        )

        if self.cluster.tls.enabled and self.cluster.tls.certificate:
            properties += self.tls_properties + self.zookeeper_tls_properties

        return properties

    @property
    def config_properties(self) -> List[str]:
        """Configure server properties from config."""
        return [
            f"{conf_key.replace('_', '.')}={str(value)}"
            for conf_key, value in self.charm_config.dict().items()
            if value is not None
        ]

    @property
    def environment(self) -> dict[str, str]:
        return map_env([
            self.kafka_opts,
            self.jmx_opts,
            self.log4j_opts,
            self.jvm_performance_opts,
            self.heap_opts,
        ])
