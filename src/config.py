#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import logging
import os
from typing import TYPE_CHECKING, Dict, List, cast

from ops.model import Unit

from literals import (
    ADMIN_USER,
    INTER_BROKER_USER,
    INTERNAL_USERS,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    REL_NAME,
    SECURITY_PROTOCOL_PORTS,
    ZK,
    AuthMechanism,
    Scope,
)
from utils import map_env, safe_get_file, safe_write_to_file, update_env

if TYPE_CHECKING:
    from charm import KafkaCharm

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


class KafkaConfig:
    """Manager for handling Kafka configuration."""

    def __init__(self, charm):
        self.charm: "KafkaCharm" = charm
        self.server_properties_filepath = f"{self.charm.snap.CONF_PATH}/server.properties"
        self.client_properties_filepath = f"{self.charm.snap.CONF_PATH}/client.properties"
        self.zk_jaas_filepath = f"{self.charm.snap.CONF_PATH}/zookeeper-jaas.cfg"
        self.keystore_filepath = f"{self.charm.snap.CONF_PATH}/keystore.p12"
        self.truststore_filepath = f"{self.charm.snap.CONF_PATH}/truststore.jks"
        self.log4j_properties_filepath = f"{self.charm.snap.CONF_PATH}/log4j.properties"
        self.jmx_prometheus_javaagent_filepath = (
            f"{self.charm.snap.BINARIES_PATH}/jmx_prometheus_javaagent.jar"
        )
        self.jmx_prometheus_config_filepath = f"{self.charm.snap.CONF_PATH}/jmx_prometheus.yaml"

    @property
    def internal_user_credentials(self) -> Dict[str, str]:
        """The charm internal usernames and passwords, e.g `sync` and `admin`.

        Returns:
            Dict of usernames and passwords
        """
        credentials = {
            user: password
            for user in INTERNAL_USERS
            if (password := self.charm.get_secret(scope="app", key=f"{user}-password"))
        }

        if not len(credentials) == len(INTERNAL_USERS):
            return {}

        return credentials

    @property
    def zookeeper_config(self) -> Dict[str, str]:
        """The config from current ZooKeeper relations for data necessary for broker connection.

        Returns:
            Dict of ZooKeeeper:
            `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`
        """
        zookeeper_config = {}
        # loop through all relations to ZK, attempt to find all needed config
        for relation in self.charm.model.relations[ZK]:
            if not relation.app:
                continue

            zk_keys = ["username", "password", "endpoints", "chroot", "uris", "tls"]
            missing_config = any(
                relation.data[relation.app].get(key, None) is None for key in zk_keys
            )

            # skip if config is missing
            if missing_config:
                continue

            # set if exists
            zookeeper_config.update(relation.data[relation.app])
            break

        if zookeeper_config:
            sorted_uris = sorted(
                zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
            )
            sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
            zookeeper_config["connect"] = ",".join(sorted_uris)

        return zookeeper_config

    @property
    def zookeeper_related(self) -> bool:
        """Checks if there is a relation with ZooKeeper.

        Returns:
            True if there is a ZooKeeper relation. Otherwise False
        """
        return bool(self.charm.model.relations[ZK])

    @property
    def zookeeper_connected(self) -> bool:
        """Checks if there is an active ZooKeeper relation with all necessary data.

        Returns:
            True if ZooKeeper is currently related with sufficient relation data
                for a broker to connect with. Otherwise False
        """
        if self.zookeeper_config.get("connect", None):
            return True

        return False

    @property
    def log4j_opts(self) -> str:
        """The Java config options for specifying log4j properties.

        Returns:
            String of Java config options
        """
        opts = [f"-Dlog4j.configuration=file:{self.log4j_properties_filepath}"]

        return f"KAFKA_LOG4J_OPTS='{' '.join(opts)}'"

    @property
    def jmx_opts(self) -> str:
        """The JMX options for configuring the prometheus exporter.

        Returns:
            String of JMX options
        """
        opts = [
            "-Dcom.sun.management.jmxremote",
            f"-javaagent:{self.jmx_prometheus_javaagent_filepath}={JMX_EXPORTER_PORT}:{self.jmx_prometheus_config_filepath}",
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
            JVM_MEM_MIN_GB if self.charm.config.profile == "testing" else JVM_MEM_MAX_GB
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
            f"-Djava.security.auth.login.config={self.zk_jaas_filepath}",
            "-Djavax.net.debug=ssl:handshake:verbose:session:keymanager:trustmanager",
        ]

        return f"KAFKA_OPTS='{' '.join(opts)}'"

    @property
    def bootstrap_server(self) -> List[str]:
        """The current Kafka uris formatted for the `bootstrap-server` command flag.

        Returns:
            List of `bootstrap-server` servers
        """
        if not self.charm.peer_relation:
            return []

        units: List[Unit] = list(set([self.charm.unit] + list(self.charm.peer_relation.units)))
        hosts = [self.charm.peer_relation.data[unit].get("private-address") for unit in units]
        port = (
            SECURITY_PROTOCOL_PORTS["SASL_SSL"].client
            if (self.charm.tls.enabled and self.charm.tls.certificate)
            else SECURITY_PROTOCOL_PORTS["SASL_PLAINTEXT"].client
        )
        return [f"{host}:{port}" for host in hosts]

    @property
    def default_replication_properties(self) -> List[str]:
        """Builds replication-related properties based on the expected app size.

        Returns:
            List of properties to be set
        """
        replication_factor = min([3, self.charm.app.planned_units()])
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
        broker_id = self.charm.unit.name.split("/")[1]
        return [
            f"broker.id={broker_id}",
            f'zookeeper.connect={self.zookeeper_config["connect"]}',
        ]

    @property
    def zookeeper_tls_properties(self) -> List[str]:
        """Builds the properties necessary for SSL connections to ZooKeeper.

        Returns:
            List of properties to be set
        """
        return [
            "zookeeper.ssl.client.enable=true",
            f"zookeeper.ssl.truststore.location={self.truststore_filepath}",
            f"zookeeper.ssl.truststore.password={self.charm.tls.truststore_password}",
            "zookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty",
        ]

    @property
    def tls_properties(self) -> List[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set
        """
        mtls = "required" if self.charm.tls.mtls_enabled else "none"
        return [
            f"ssl.truststore.location={self.truststore_filepath}",
            f"ssl.truststore.password={self.charm.tls.truststore_password}",
            f"ssl.keystore.location={self.keystore_filepath}",
            f"ssl.keystore.password={self.charm.tls.keystore_password}",
            f"ssl.client.auth={mtls}",
        ]

    @property
    def scram_properties(self) -> List[str]:
        """Builds the properties for each scram listener.

        Returns:
            list of scram properties to be set
        """
        username = INTER_BROKER_USER
        password = self.internal_user_credentials.get(INTER_BROKER_USER, "")

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
            if (self.charm.tls.enabled and self.charm.tls.certificate)
            else "SASL_PLAINTEXT"
        )

    @property
    def auth_mechanisms(self) -> List[AuthMechanism]:
        """Return a list of enabled auth mechanisms."""
        # TODO: At the moment only one mechanism for extra listeners. Will need to be
        # extended with more depending on configuration settings.
        protocol = [self.security_protocol]
        if self.charm.tls.mtls_enabled:
            protocol += ["SSL"]

        return cast(List[AuthMechanism], protocol)

    @property
    def internal_listener(self) -> Listener:
        """Return the internal listener."""
        protocol = self.security_protocol
        return Listener(host=self.charm.unit_host, protocol=protocol, scope="INTERNAL")

    @property
    def client_listeners(self) -> List[Listener]:
        """Return a list of extra listeners."""
        # if there is a relation with kafka then add extra listener
        if not self.charm.model.relations.get(REL_NAME, None):
            return []

        return [
            Listener(host=self.charm.unit_host, protocol=auth, scope="CLIENT")
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
        super_users = set(INTERNAL_USERS)
        for relation in self.charm.model.relations[REL_NAME]:
            if not relation or not relation.app or not self.charm.peer_relation:
                continue

            extra_user_roles = relation.data[relation.app].get("extra-user-roles", "")
            password = self.charm.peer_relation.data[self.charm.app].get(
                f"relation-{relation.id}", None
            )
            # if passwords are set for client admins, they're good to load
            if "admin" in extra_user_roles and password is not None:
                super_users.add(f"relation-{relation.id}")

        super_users_arg = sorted([f"User:{user}" for user in super_users])

        return ";".join(super_users_arg)

    @property
    def log_dirs(self) -> str:
        """Builds the necessary log.dirs based on mounted storage volumes.

        Returns:
            String of log.dirs property value to be set
        """
        return ",".join(
            [os.fspath(storage.location) for storage in self.charm.model.storages["data"]]
        )

    @property
    def rack_properties(self) -> List[str]:
        """Builds all properties related to rack awareness configuration.

        Returns:
            List of properties to be set
        """
        # TODO: not sure if we should make this an instance attribute like the other paths
        rack_path = f"{self.charm.snap.CONF_PATH}/rack.properties"
        return safe_get_file(rack_path) or []

    @property
    def client_properties(self) -> List[str]:
        """Builds all properties necessary for running an admin Kafka client.

        This includes SASL/SCRAM auth and security mechanisms.

        Returns:
            List of properties to be set
        """
        username = ADMIN_USER
        password = self.internal_user_credentials.get(ADMIN_USER, "")

        client_properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
            "sasl.mechanism=SCRAM-SHA-512",
            f"security.protocol={self.security_protocol}",  # FIXME: will need changing once multiple listener auth schemes
            f"bootstrap.servers={','.join(self.bootstrap_server)}",
        ]

        if self.charm.tls.enabled and self.charm.tls.certificate:
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
                f"inter.broker.protocol.version={self.charm.upgrade.current_version}",
            ]
            + self.config_properties
            + self.scram_properties
            + self.default_replication_properties
            + self.auth_properties
            + self.rack_properties
            + DEFAULT_CONFIG_OPTIONS.split("\n")
        )

        if self.charm.tls.enabled and self.charm.tls.certificate:
            properties += self.tls_properties + self.zookeeper_tls_properties

        return properties

    @property
    def config_properties(self) -> List[str]:
        """Configure server properties from config."""
        return [
            f"{conf_key.replace('_', '.')}={str(value)}"
            for conf_key, value in self.charm.config.dict().items()
            if value is not None
        ]

    def set_zk_jaas_config(self) -> None:
        """Writes the ZooKeeper JAAS config using ZooKeeper relation data."""
        jaas_config = f"""
            Client {{
                org.apache.zookeeper.server.auth.DigestLoginModule required
                username="{self.zookeeper_config['username']}"
                password="{self.zookeeper_config['password']}";
            }};
        """
        safe_write_to_file(content=jaas_config, path=self.zk_jaas_filepath, mode="w")

    def set_server_properties(self) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        safe_write_to_file(
            content="\n".join(self.server_properties),
            path=self.server_properties_filepath,
            mode="w",
        )

    def set_client_properties(self) -> None:
        """Writes all client config properties to the `client.properties` path."""
        safe_write_to_file(
            content="\n".join(self.client_properties),
            path=self.client_properties_filepath,
            mode="w",
        )

    def set_environment(self) -> None:
        """Writes the env-vars needed for passing to charmed-kafka service."""
        updated_env_list = [
            self.kafka_opts,
            self.jmx_opts,
            self.log4j_opts,
            self.jvm_performance_opts,
            self.heap_opts,
        ]
        update_env(env=map_env(env=updated_env_list))
