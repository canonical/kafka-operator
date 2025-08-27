#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka configuration."""

import json
import logging
import os
import re
import textwrap
from abc import abstractmethod
from functools import cached_property
from typing import Iterable, cast

from lightkube.core.exceptions import ApiError
from typing_extensions import override

from core.cluster import ClusterState
from core.models import PeerCluster
from core.structured_config import CharmConfig, LogLevel
from core.workload import CharmedKafkaPaths, WorkloadBase
from literals import (
    ADMIN_USER,
    BALANCER,
    BALANCER_GOALS_TESTING,
    BROKER,
    CONTROLLER_USER,
    DEFAULT_BALANCER_GOALS,
    HARD_BALANCER_GOALS,
    INTER_BROKER_USER,
    JMX_CC_PORT,
    JMX_EXPORTER_PORT,
    JVM_MEM_MAX_GB,
    JVM_MEM_MIN_GB,
    KRAFT_NODE_ID_OFFSET,
    PATHS,
    PROFILE_TESTING,
    SECURITY_PROTOCOL_PORTS,
    SUBSTRATE,
    AuthMap,
    Scope,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_OPTIONS = """
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-512
allow.everyone.if.no.acl.found=false
auto.create.topics.enable=false
"""
KAFKA_CRUISE_CONTROL_OPTIONS = """
metric.reporters=com.linkedin.kafka.cruisecontrol.metricsreporter.CruiseControlMetricsReporter
"""
TESTING_OPTIONS = """
cruise.control.metrics.reporter.metrics.reporting.interval.ms=6000
"""
CRUISE_CONTROL_CONFIG_OPTIONS = """
metric.reporter.topic=__CruiseControlMetrics
sample.store.class=com.linkedin.kafka.cruisecontrol.monitor.sampling.KafkaSampleStore
topic.config.provider.class=com.linkedin.kafka.cruisecontrol.config.KafkaAdminTopicConfigProvider
kafka.broker.failure.detection.enable=true
partition.metric.sample.store.topic=__KafkaCruiseControlPartitionMetricSamples
broker.metric.sample.store.topic=__KafkaCruiseControlModelTrainingSamples
max.active.user.tasks=10
default.api.timeout.ms=20000
request.timeout.ms=10000
"""
# Divided periods by 10
CRUISE_CONTROL_TESTING_OPTIONS = """
cruise.control.metrics.reporter.metrics.reporting.interval.ms=6000
broker.metrics.window.ms=30000
partition.metrics.window.ms=30000
metadata.max.age.ms=10000
metric.sampling.interval.ms=12000
min.samples.per.broker.metrics.window=1
min.samples.per.partition.metrics.window=1
num.partition.metrics.windows=3
num.broker.metrics.windows=10
default.api.timeout.ms=10000
request.timeout.ms=5000
"""
SERVER_PROPERTIES_BLACKLIST = [
    "profile",
    "log_level",
    "certificate_extra_sans",
    "extra_listeners",
    "roles",
    "expose_external",
    "system_users",
]


class Listener:
    """Definition of a listener.

    Args:
        auth_map: AuthMap representing the auth.protocol and auth.mechanism for the listener
        scope: scope of the listener, CLIENT, INTERNAL, EXTERNAL or EXTRA
        host: string with the host that will be announced
        baseport (optional): integer port to offset CLIENT port numbers for EXTRA listeners
        node_port (optional): the node-port for the listener if scope=EXTERNAL
    """

    def __init__(
        self,
        auth_map: AuthMap,
        scope: Scope,
        host: str = "",
        baseport: int = 30000,
        extra_count: int = -1,
        node_port: int | None = None,
    ):
        self.auth_map = auth_map
        self.protocol = auth_map.protocol
        self.mechanism = auth_map.mechanism
        self.host = host
        self._scope: Scope = scope
        self.baseport = baseport
        self.extra_count = extra_count
        self.node_port = node_port

    @property
    def scope(self) -> Scope:
        """Internal scope validator."""
        return cast(Scope, self._scope)

    @scope.setter
    def scope(self, value):
        """Internal scope validator."""
        if value not in ["CLIENT", "INTERNAL", "EXTERNAL", "EXTRA"]:
            raise ValueError("Only CLIENT, INTERNAL, EXTERNAL and EXTRA scopes are accepted")

        self._scope = cast(Scope, value)

    @property
    def port(self) -> int:
        """Port associated with the protocol/scope.

        Returns:
            Integer of port number
        """
        # generates ports 39092, 39192, 39292 etc for listener auth if baseport=30000
        if self.scope == "EXTRA":
            return getattr(SECURITY_PROTOCOL_PORTS[self.auth_map], "client") + self.baseport

        return getattr(SECURITY_PROTOCOL_PORTS[self.auth_map], self.scope.lower())

    @property
    def name(self) -> str:
        """Name of the listener."""
        return f"{self.scope}_{self.protocol}_{self.mechanism.replace('-', '_')}" + (
            f"_{self.extra_count}" if self.extra_count >= 0 else ""
        )

    @property
    def protocol_map(self) -> str:
        """Return `name:protocol`."""
        return f"{self.name}:{self.protocol}"

    @property
    def listener(self) -> str:
        """Return `name://0.0.0.0:port`."""
        return f"{self.name}://0.0.0.0:{self.port}"

    @property
    def advertised_listener(self) -> str:
        """Return `name://host:port`."""
        if self.scope == "EXTERNAL":
            return f"{self.name}://{self.host}:{self.node_port}"

        return f"{self.name}://{self.host}:{self.port}"


class CommonConfigManager:
    """Common options for managing Kafka configuration."""

    config: CharmConfig
    workload: WorkloadBase
    state: ClusterState

    @cached_property
    def peer_cluster_state(self) -> PeerCluster:
        """Cached peer_cluster state."""
        return self.state.peer_cluster

    @property
    def log_level(self) -> str:
        """Return the Java-compliant logging level set by the user.

        Returns:
            String with these possible values: DEBUG, INFO, WARN, ERROR
        """
        # Remapping to WARN that is generally used in Java applications based on log4j and logback.
        if self.config.log_level == LogLevel.WARNING.value:
            return "KAFKA_CFG_LOGLEVEL=WARN"

        return f"KAFKA_CFG_LOGLEVEL={self.config.log_level}"

    @property
    def kafka_jmx_opts(self) -> str:
        """The JMX options for configuring the prometheus exporter.

        Returns:
            String of JMX options
        """
        opts = [
            "-Dcom.sun.management.jmxremote",
            f"-javaagent:{CharmedKafkaPaths(BROKER).jmx_prometheus_javaagent}={JMX_EXPORTER_PORT}:{self.workload.paths.jmx_prometheus_config}",
        ]

        return f"KAFKA_JMX_OPTS='{' '.join(opts)}'"

    @property
    def cc_jmx_opts(self) -> str:
        """The JMX options for configuring the prometheus exporter on cruise control.

        Returns:
            String of JMX options
        """
        opts = [
            "-Dcom.sun.management.jmxremote",
            f"-javaagent:{CharmedKafkaPaths(BROKER).jmx_prometheus_javaagent}={JMX_CC_PORT}:{self.workload.paths.jmx_cc_config}",
        ]

        return f"CC_JMX_OPTS='{' '.join(opts)}'"

    @property
    def tools_log4j_opts(self) -> str:
        """The Log4j options for configuring the tooling logging.

        Returns:
            String of Log4j options
        """
        opts = [
            f'-Dlog4j.configuration=file:{self.workload.paths.tools_log4j_properties} -Dcharmed.kafka.log.level={self.log_level.split("=")[1]}'
        ]

        return f"KAFKA_LOG4J_OPTS='{' '.join(opts)}'"

    @property
    @abstractmethod
    def kafka_opts(self) -> str:
        """Extra Java config options.

        Returns:
            String of Java config options
        """
        ...

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
    def auxiliary_paths(self) -> list[str]:
        """Auxiliary environment variables for logs, config and other useful base paths."""
        if SUBSTRATE == "k8s":
            return []

        if self.state.runs_broker or self.state.runs_controller:
            return [f"{key}={path}" for key, path in PATHS["kafka"].items()]

        return [f"{key}={path}" for key, path in PATHS["cruise-control"].items()]


class ConfigManager(CommonConfigManager):
    """Manager for handling Kafka configuration."""

    def __init__(
        self,
        state: ClusterState,
        workload: WorkloadBase,
        config: CharmConfig,
    ):
        self.state = state
        self.workload = workload
        self.config = config

    @property
    @override
    def kafka_opts(self) -> str:
        opts = []

        http_proxy = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        https_proxy = os.environ.get("JUJU_CHARM_HTTPS_PROXY")
        no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY")

        for prot, proxy in {"http": http_proxy, "https": https_proxy}.items():
            if proxy:
                proxy = re.sub(r"^https?://", "", proxy)
                [host, port] = proxy.split(":") if ":" in proxy else [proxy, "8080"]
                opts.append(f"-D{prot}.proxyHost={host} -D{prot}.proxyPort={port}")
        if no_proxy:
            opts.append(f"-Dhttp.nonProxyHosts={no_proxy}")

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
    def tls_properties(self) -> list[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set
        """
        properties = []

        # Internal listeners always use TLS regardless.
        for listener in self.controller_listeners + [self.internal_listener]:
            listener_name = listener.name.lower()
            properties += [
                f"listener.name.{listener_name}.ssl.truststore.location={self.workload.paths.peer_truststore}",
                f"listener.name.{listener_name}.ssl.truststore.password={self.state.unit_broker.truststore_password}",
                f"listener.name.{listener_name}.ssl.keystore.location={self.workload.paths.peer_keystore}",
                f"listener.name.{listener_name}.ssl.keystore.password={self.state.unit_broker.keystore_password}",
            ]

        if not all([self.state.cluster.tls_enabled, self.state.unit_broker.client_certs.ready]):
            return properties

        return properties + [
            f"ssl.truststore.location={self.workload.paths.truststore}",
            f"ssl.truststore.password={self.state.unit_broker.truststore_password}",
            f"ssl.keystore.location={self.workload.paths.keystore}",
            f"ssl.keystore.password={self.state.unit_broker.keystore_password}",
        ]

    @property
    def client_tls_properties(self) -> list[str]:
        """Builds the properties necessary for TLS authentication of clients, either internal or KRaft.

        Returns:
            List of properties to be set
        """
        return [
            f"ssl.truststore.location={self.workload.paths.peer_truststore}",
            f"ssl.truststore.password={self.state.unit_broker.truststore_password}",
            f"ssl.keystore.location={self.workload.paths.peer_keystore}",
            f"ssl.keystore.password={self.state.unit_broker.keystore_password}",
        ]

    @property
    def mtls_properties(self) -> list[str]:
        """Builds the properties necessary for MTLS authentication.

        Returns:
            List of properties to be set
        """
        if not self.state.has_mtls_clients:
            return []

        return ["ssl.client.auth=required"]

    @property
    def scram_properties(self) -> list[str]:
        """Builds the properties for each SCRAM listener.

        Returns:
            list of SCRAM properties to be set
        """
        username = INTER_BROKER_USER
        password = self.state.cluster.internal_user_credentials.get(INTER_BROKER_USER, "")

        listener_name = self.internal_listener.name.lower()
        listener_mechanism = self.internal_listener.mechanism.lower()

        admin_usermame = ADMIN_USER
        admin_password = self.state.cluster.internal_user_credentials.get(ADMIN_USER, "")

        # Related to KAFKA-15513: we should add admin user to the internal listener in case of premature bootstrap
        scram_properties = [
            f'listener.name.{listener_name}.{listener_mechanism}.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}" user_{admin_usermame}="{admin_password}" user_{username}="{password}";',
            f"listener.name.{listener_name}.sasl.enabled.mechanisms={self.internal_listener.mechanism}",
        ]
        for auth in self.client_listeners + self.external_listeners + self.extra_listeners:
            if not auth.mechanism.startswith("SCRAM"):
                continue

            scram_properties.append(
                f'listener.name.{auth.name.lower()}.{auth.mechanism.lower()}.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";'
            )
            scram_properties.append(
                f"listener.name.{auth.name.lower()}.sasl.enabled.mechanisms={auth.mechanism}"
            )

        return scram_properties

    @property
    def controller_scram_properties(self) -> list[str]:
        """Builds the SCRAM properties for controller listener.

        Returns:
            list of SCRAM properties to be set
        """
        password = self.peer_cluster_state.controller_password
        listeners = []

        for listener in self.controller_listeners:
            listener_mechanism = listener.mechanism.lower()
            listener_name = listener.name.lower()

            listeners += [
                f"sasl.mechanism.controller.protocol={listener.mechanism}",
                f'listener.name.{listener_name}.{listener_mechanism}.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{CONTROLLER_USER}" password="{password}" user_{CONTROLLER_USER}="{password}";',
                f"listener.name.{listener_name}.sasl.enabled.mechanisms={listener.mechanism}",
            ]

        return listeners

    @property
    def controller_kraft_client_properties(self) -> list[str]:
        """Builds the SCRAM properties for controller' KRaft client to be able to communicate with quorum manager.

        Returns:
            list of KRaft client properties to be set
        """
        password = self.peer_cluster_state.controller_password

        # Strip CC & TLS properties from KRaft quorum client properties file
        stripped_properties = list(
            set(self.server_properties)
            - set(
                KAFKA_CRUISE_CONTROL_OPTIONS.splitlines()
                + self.metrics_reporter_properties
                + self.tls_properties
            )
        )
        stripped_properties.sort()

        return (
            stripped_properties
            + [
                f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{CONTROLLER_USER}" password="{password}";',
                f"sasl.mechanism={self.internal_listener.mechanism}",
                f"security.protocol={self.internal_listener.protocol}",
                "default.api.timeout.ms=20000",
                "request.timeout.ms=10000",
            ]
            + self.client_tls_properties
        )

    @property
    def oauth_properties(self) -> list[str]:
        """Builds the properties for the oauth listener.

        Returns:
            list of oauth properties to be set.
        """
        if not self.state.oauth_relation:
            return []

        listener = [
            listener
            for listener in self.client_listeners
            if listener.mechanism.startswith("OAUTH")
        ][0]

        username_claim = "email"
        username_fallback_claim = "client_id"

        # use jwks validation if jwt token, otherwise use introspection validation
        validation_cfg = (
            f'oauth.jwks.endpoint.uri="{self.state.oauth.jwks_endpoint}"'
            if self.state.oauth.jwt_access_token
            else f'oauth.introspection.endpoint.uri="{self.state.oauth.introspection_endpoint}"'
        )

        truststore_cfg = ""
        if not self.state.oauth.uses_trusted_ca:
            truststore_cfg = f'oauth.ssl.truststore.location="{self.workload.paths.truststore}" oauth.ssl.truststore.password="{self.state.unit_broker.truststore_password}" oauth.ssl.truststore.type="JKS"'

        oauth_properties = [
            textwrap.dedent(
                f"""\
                listener.name.{listener.name.lower()}.{listener.mechanism.lower()}.sasl.jaas.config=org.apache.kafka.common.security.oauthbearer.OAuthBearerLoginModule required \\
                    oauth.client.id="kafka" \\
                    oauth.valid.issuer.uri="{self.state.oauth.issuer_url}" \\
                    {validation_cfg} \\
                    oauth.username.claim="{username_claim}" \\
                    oauth.fallback.username.claim="{username_fallback_claim}" \\
                    oauth.check.audience="true" \\
                    oauth.check.access.token.type="false" \\
                    oauth.config.id="{listener.name}" \\
                    unsecuredLoginStringClaim_sub="unused" \\
                    {truststore_cfg};"""
            ),
            f"listener.name.{listener.name.lower()}.{listener.mechanism.lower()}.sasl.server.callback.handler.class=io.strimzi.kafka.oauth.server.JaasServerOauthValidatorCallbackHandler",
            f"listener.name.{listener.name.lower()}.sasl.enabled.mechanisms={listener.mechanism}",
            "principal.builder.class=io.strimzi.kafka.oauth.server.OAuthKafkaPrincipalBuilder",
        ]

        return oauth_properties

    @property
    def internal_listener(self) -> Listener:
        """Return the internal listener."""
        return Listener(
            host=self.state.unit_broker.internal_address,
            auth_map=self.state.internal_auth,
            scope="INTERNAL",
        )

    @property
    def active_controller_listener(self) -> Listener:
        """Returns the active (current) controller listener."""
        return Listener(
            host=self.state.unit_broker.internal_address,
            auth_map=self.state.internal_auth,
            scope="CONTROLLER",
        )

    @property
    def controller_listeners(self) -> list[Listener]:
        """Return all controller listeners including those used in controller listener upgrades."""
        return [self.active_controller_listener]

    @property
    def extra_listeners(self) -> list[Listener]:
        """Return a list of extra listeners."""
        extra_host_baseports = [
            tuple(listener.split(":"))
            for listener in self.config.extra_listeners
            if ":" in listener
        ]

        extra_listeners = []
        extra_count = 0
        for host, baseport in extra_host_baseports:
            for auth_map in self.state.enabled_auth:
                host = host.replace("{unit}", str(self.state.unit_broker.unit_id))
                extra_listeners.append(
                    Listener(
                        host=host,
                        auth_map=auth_map,
                        scope="EXTRA",
                        baseport=int(baseport),
                        extra_count=extra_count,
                    )
                )

            extra_count += 1

        return extra_listeners

    @property
    def client_listeners(self) -> list[Listener]:
        """Return a list of client listeners."""
        return [
            Listener(
                host=self.state.unit_broker.internal_address, auth_map=auth_map, scope="CLIENT"
            )
            for auth_map in self.state.enabled_auth
        ]

    @property
    def external_listeners(self) -> list[Listener]:
        """Return a list of extra listeners."""
        if not self.config.expose_external:
            return []

        listeners = []
        for auth in self.state.enabled_auth:
            node_port = 0
            try:
                node_port = self.state.unit_broker.k8s.get_listener_nodeport(auth)
            except ApiError as e:
                # don't worry about defining a service during cluster init
                # as it doesn't exist yet to `kubectl get`
                logger.debug(e)
                continue

            if not node_port:
                continue

            listeners.append(
                Listener(
                    auth_map=auth,
                    scope="EXTERNAL",
                    host=self.state.unit_broker.node_ip,
                    # default in case service not created yet during cluster init
                    # will resolve during config-changed
                    node_port=node_port,
                )
            )

        return listeners

    @property
    def all_listeners(self) -> list[Listener]:
        """Return a list with all expected listeners."""
        return (
            [self.internal_listener]
            + self.client_listeners
            + self.external_listeners
            + self.extra_listeners
            + (self.controller_listeners if self.state.runs_controller else [])
        )

    @property
    def rack_properties(self) -> list[str]:
        """Builds all properties related to rack awareness configuration.

        Returns:
            List of properties to be set
        """
        rack_path = f"{self.workload.paths.conf_path}/rack.properties"
        return self.workload.read(rack_path) or []

    @property
    def rack(self) -> str:
        """The rack for the current running unit, determined from a manually added `rack.properties`.

        Returns:
            String of broker.rack value.
        """
        for item in self.rack_properties:
            if "broker.rack" in item:
                return item.split("=")[1]

        return ""

    def _build_internal_client_properties(
        self, username: str, prefix: str | None = None
    ) -> list[str]:
        """Builds all properties necessary for running an internal Kafka client.

        This includes SASL/SCRAM auth and security mechanisms.

        Args:
            username: the username to set. Must be from `INTERNAL_USERS`
            prefix: any prefix to assign to the properties to indicate a specific client
                e.g `cruise.control.metrics.reporter` -> `cruise.control.metrics.reporter.bootstrap.servers`

        Returns:
            List of properties to be set on the Kafka broker
        """
        password = self.state.cluster.internal_user_credentials.get(username, "")

        properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
            f"sasl.mechanism={self.state.internal_auth.mechanism}",
            f"security.protocol={self.state.internal_auth.protocol}",
            f"bootstrap.servers={self.state.bootstrap_server_internal}",
        ] + self.client_tls_properties

        return [f"{prefix}.{prop}" if prefix else prop for prop in properties]

    @property
    def client_properties(self) -> list[str]:
        """Builds all properties necessary for running an admin Kafka client."""
        return self._build_internal_client_properties(username=ADMIN_USER)

    @property
    def metrics_reporter_properties(self) -> list[str]:
        """Builds all the properties necessary for running the CruiseControlMetricsReporter client."""
        return self._build_internal_client_properties(
            username=ADMIN_USER, prefix="cruise.control.metrics.reporter"
        )

    @property
    def authorizer_class(self) -> list[str]:
        """Return the authorizer Java class used on Kafka."""
        return ["authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer"]

    @property
    def controller_properties(self) -> list[str]:
        """Builds all properties necessary for starting Kafka controller service.

        Returns:
            List of properties to be set
        """
        roles = []
        node_id = self.state.unit_broker.unit_id
        if self.state.runs_broker:
            roles.append("broker")
            node_id += KRAFT_NODE_ID_OFFSET
        if self.state.runs_controller:
            roles.append("controller")

        properties = [
            f"process.roles={','.join(roles)}",
            f"node.id={node_id}",
            f"controller.quorum.bootstrap.servers={self.peer_cluster_state.bootstrap_controller}",
            f"controller.listener.names={','.join([listener.name for listener in self.controller_listeners])}",
            *self.controller_scram_properties,
        ]

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
        controller_listeners = [
            listener.advertised_listener for listener in self.controller_listeners
        ]
        controller_protocol_map = [listener.protocol_map for listener in self.controller_listeners]

        # NOTE: Case where the controller is running standalone. Early return with a
        # smaller subset of config options
        if self.state.runs_controller_only:
            properties = (
                [
                    f"super.users={self.state.super_users}",
                    f"log.dirs={self.state.log_dirs}",
                    f"listeners={','.join(controller_listeners)}",
                    f"listener.security.protocol.map={','.join(controller_protocol_map)}",
                ]
                + self.controller_properties
                + self.authorizer_class
                + self.tls_properties
                # TODO: might want to add self.mtls_properties
            )
            return properties

        if self.state.runs_broker_only:
            # KRaft, broker only: we don't need the listener, but still need the protocol mapping
            protocol_map += controller_protocol_map

        properties = (
            [
                f"super.users={self.state.super_users}",
                f"log.dirs={self.state.log_dirs}",
                f"listener.security.protocol.map={','.join(protocol_map)}",
                f"listeners={','.join(listeners_repr)}",
                f"advertised.listeners={','.join(advertised_listeners)}",
                f"inter.broker.listener.name={self.internal_listener.name}",
            ]
            + self.scram_properties
            + self.oauth_properties
            + self.config_properties
            + self.default_replication_properties
            + self.rack_properties
            + DEFAULT_CONFIG_OPTIONS.split("\n")
            + self.authorizer_class
            + self.controller_properties
            + self.tls_properties
            + self.mtls_properties
        )

        if self.state.runs_balancer or BALANCER.value in self.peer_cluster_state.roles:
            properties += KAFKA_CRUISE_CONTROL_OPTIONS.splitlines()
            properties += self.metrics_reporter_properties

        if self.config.profile == PROFILE_TESTING:
            properties += TESTING_OPTIONS.split("\n")

        return properties

    @property
    def config_properties(self) -> list[str]:
        """Configure server properties from config."""
        return [
            f"{self._translate_config_key(conf_key)}={str(value)}"
            for conf_key, value in self.config.dict().items()
            if value is not None
        ]

    def set_server_properties(self) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        self.workload.write(
            content="\n".join(self.server_properties), path=self.workload.paths.server_properties
        )

    def set_client_properties(self) -> None:
        """Writes all client config properties to the `client.properties` and `kraft-client.properties` paths."""
        self.workload.write(
            content="\n".join(self.client_properties), path=self.workload.paths.client_properties
        )
        self.workload.write(
            content="\n".join(self.controller_kraft_client_properties),
            path=self.workload.paths.kraft_client_properties,
        )

    def set_environment(self) -> None:
        """Writes the env-vars needed for passing to charmed-kafka service."""
        updated_env_list = [
            self.kafka_opts,
            self.kafka_jmx_opts,
            self.cc_jmx_opts,
            self.jvm_performance_opts,
            self.heap_opts,
            self.log_level,
        ] + self.auxiliary_paths

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


class BalancerConfigManager(CommonConfigManager):
    """Manager for handling Balancer configuration."""

    def __init__(
        self,
        state: ClusterState,
        workload: WorkloadBase,
        config: CharmConfig,
    ):
        self.state = state
        self.workload = workload
        self.config = config

    @property
    @override
    def kafka_opts(self) -> str:
        opts = [
            f"-Djava.security.auth.login.config={self.workload.paths.balancer_jaas}",
        ]

        return f"KAFKA_OPTS='{' '.join(opts)}'"

    @property
    def balance_thresholds(self) -> list[str]:
        """Properties for managing variance in inter-broker resource usage."""
        balance_threshold = self.config.cruisecontrol_balance_threshold
        return [
            f"cpu.balance.threshold={balance_threshold}",
            f"disk.balance.threshold={balance_threshold}",
            f"network.inbound.balance.threshold={balance_threshold}",
            f"network.outbound.balance.threshold={balance_threshold}",
            f"replica.count.balance.threshold={balance_threshold}",
            f"leader.replica.count.balance.threshold={balance_threshold}",
        ]

    @property
    def capacity_thresholds(self) -> list[str]:
        """Properties for managing broker resource usage total capacity."""
        capacity_threshold = self.config.cruisecontrol_capacity_threshold
        return [
            f"disk.capacity.threshold={capacity_threshold}",
            f"cpu.capacity.threshold={capacity_threshold}",
            f"network.inbound.capacity.threshold={capacity_threshold}",
            f"network.outbound.capacity.threshold={capacity_threshold}",
        ]

    @property
    def goals(self) -> list[str]:
        """Builds all pluggable Goals properties for CruiseControl.

        Returns:
            List of properties to be set
        """
        goals = DEFAULT_BALANCER_GOALS

        if self.config.profile == PROFILE_TESTING:
            goals = BALANCER_GOALS_TESTING

        if self.peer_cluster_state.racks:
            if (
                min(
                    [3, len(self.peer_cluster_state.broker_capacities.get("brokerCapacities", []))]
                )
                > self.peer_cluster_state.racks
            ):  # replication-factor > racks is not ideal
                goals = goals + ["RackAwareDistribution"]
            else:
                goals = goals + ["RackAware"]

        default_goals = [
            f"com.linkedin.kafka.cruisecontrol.analyzer.goals.{goal}Goal" for goal in goals
        ]

        return [
            f"default.goals={','.join(default_goals)}",
            f"goals={','.join(default_goals)}",
            f"hard.goals={','.join([goal for goal in default_goals if any(hard_goal in goal for hard_goal in HARD_BALANCER_GOALS)])}",
        ]

    @property
    def cc_tls_properties(self) -> list[str]:
        """Builds the properties necessary for TLS authentication.

        Returns:
            List of properties to be set
        """
        return [
            f"ssl.truststore.location={self.workload.paths.peer_truststore}",
            f"ssl.truststore.password={self.state.unit_broker.truststore_password}",
            f"ssl.keystore.location={self.workload.paths.peer_keystore}",
            f"ssl.keystore.password={self.state.unit_broker.keystore_password}",
            "ssl.client.auth=none",  # TODO mTLS related. Will need changing if mTLS is introduced
        ]

    @property
    def cruise_control_properties(self) -> list[str]:
        """Builds all properties necessary for starting Cruise Control service.

        Returns:
            List of properties to be set
        """
        properties = (
            [
                f"bootstrap.servers={self.peer_cluster_state.broker_uris}",
                f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{self.peer_cluster_state.broker_username}" password="{self.peer_cluster_state.broker_password}";',
                f"sasl.mechanism={self.state.internal_auth.mechanism}",
                f"security.protocol={self.state.internal_auth.protocol}",
                f"capacity.config.file={self.workload.paths.capacity_jbod_json}",
                "webserver.security.enable=true",
                f"webserver.auth.credentials.file={self.workload.paths.cruise_control_auth}",
            ]
            + CRUISE_CONTROL_CONFIG_OPTIONS.split("\n")
            + self.goals
            + self.cc_tls_properties
        )

        if self.config.profile == PROFILE_TESTING:
            properties += CRUISE_CONTROL_TESTING_OPTIONS.split("\n")

        return properties

    def set_cruise_control_properties(self) -> None:
        """Writes all Cruise Control properties to the `cruisecontrol.properties` path."""
        self.workload.write(
            content="\n".join(self.cruise_control_properties),
            path=self.workload.paths.cruise_control_properties,
        )

    def set_broker_capacities(self) -> None:
        """Writes all broker storage capacities to `capacityJBOD.json`."""
        self.workload.write(
            content=json.dumps(self.peer_cluster_state.broker_capacities),
            path=self.workload.paths.capacity_jbod_json,
        )

    def set_environment(self) -> None:
        """Writes the env-vars needed for passing to charmed-kafka service.

        We avoid overwriting KAFKA_OPTS in /etc/environment because it is only used by the broker.
        """
        updated_env_list = [
            self.kafka_jmx_opts,
            self.cc_jmx_opts,
            self.jvm_performance_opts,
            self.heap_opts,
            self.log_level,
            self.kafka_opts,
        ] + self.auxiliary_paths

        raw_current_env = self.workload.read("/etc/environment")
        current_env = map_env(raw_current_env)

        updated_env = current_env | map_env(updated_env_list)
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])

        if not self.state.runs_broker:
            self.workload.write(content=content, path="/etc/environment")

    def set_cruise_control_auth(self) -> None:
        """Write the credentials file for Cruise Control authentication."""
        self.workload.write(
            content=f"{self.state.cluster.balancer_username}: {self.state.cluster.balancer_password},ADMIN\n",
            path=self.workload.paths.cruise_control_auth,
        )


def map_env(env: Iterable[str]) -> dict[str, str]:
    """Parse env var into a dict."""
    map_env = {}
    for var in env:
        key = "".join(var.split("=", maxsplit=1)[0])
        value = "".join(var.split("=", maxsplit=1)[1:])
        if key:
            # only check for keys, as we can have an empty value for a variable
            map_env[key] = value
    return map_env
