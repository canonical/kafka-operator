#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka Kubernetes resources for a single Kafka pod."""

import json
import logging
import math
import time
from functools import cache

from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta, OwnerReference
from lightkube.resources.core_v1 import Node, Pod, Service

from literals import SECURITY_PROTOCOL_PORTS, AuthMap, AuthMechanism

# default logging from lightkube httpx requests is very noisy
logging.getLogger("lightkube").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)


class K8sManager:
    """Manager for handling Kafka Kubernetes resources for a single Kafka pod."""

    def __init__(
        self,
        pod_name: str,
        namespace: str,
    ):
        self.pod_name = pod_name
        self.app_name = "-".join(pod_name.split("-")[:-1])
        self.namespace = namespace
        self.bootstrap_service_name = f"{self.app_name}-bootstrap"
        self.short_auth_mechanism_mapping: dict[AuthMechanism, str] = {
            "SCRAM-SHA-512": "scram",
            "OAUTHBEARER": "oauth",
            "SSL": "ssl",
        }

    def __eq__(self, other: object) -> bool:
        """__eq__ dunder.

        Needed to get an cache hit on calls on the same method from different instances of K8sManager
        as `self` is passed to methods.
        """
        return isinstance(other, K8sManager) and self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        """__hash__ dunder.

        K8sManager needs to be hashable so that `self` can be passed to the 'dict-like' cache.
        """
        return hash(json.dumps(self.__dict__, sort_keys=True))

    @property
    def client(self) -> Client:
        """The Lightkube client."""
        return Client(  # pyright: ignore[reportArgumentType]
            field_manager=self.pod_name,
            namespace=self.namespace,
        )

    @staticmethod
    def get_ttl_hash(seconds=60 * 2) -> int:
        """Gets a unique time hash for the cache, expiring after 2 minutes.

        When 2m has passed, a new value will be created, ensuring an cache miss
        and a re-loading of that K8s API call.
        """
        return math.floor(time.time() / seconds)

    # --- GETTERS ---

    def get_pod(self, pod_name: str = "") -> Pod:
        """Gets the Pod via the K8s API."""
        return self._get_pod(pod_name, self.get_ttl_hash())

    def get_node(self, pod_name: str) -> Node:
        """Gets the Node the Pod is running on via the K8s API."""
        return self._get_node(pod_name, self.get_ttl_hash())

    def get_node_ip(self, pod_name: str) -> str:
        """Gets the IP Address of the Node of a given Pod via the K8s API."""
        return self._get_node_ip(pod_name, self.get_ttl_hash())

    def get_service(self, service_name: str) -> Service | None:
        """Gets the Service via the K8s API."""
        return self._get_service(service_name, self.get_ttl_hash())

    # SERVICE BUILDERS

    def get_node_port(
        self,
        service: Service,
        auth_map: AuthMap,
    ) -> int:
        """Gets the NodePort number for the service via the K8s API."""
        if not service.spec or not service.spec.ports:
            raise Exception("Could not find Service spec or ports")

        for port in service.spec.ports:
            if (
                auth_map.protocol.lower().replace("_", "-") in port.name
                and self.short_auth_mechanism_mapping[auth_map.mechanism] in port.name
            ):
                return port.nodePort

        raise Exception(
            f"Unable to find NodePort using {auth_map.protocol} and {auth_map.mechanism} for the {service} service"
        )

    def build_listener_service_name(self, auth_map: AuthMap):
        """Builds the Service name for a given auth.protocol and auth.mechanism.

        Returns:
            String of listener service name
                e.g `kafka-0-sasl-plaintext-scram`, `kafka-12-sasl-ssl-oauth`
        """
        return f"{self.pod_name}-{auth_map.protocol.lower().replace('_','-')}-{self.short_auth_mechanism_mapping[auth_map.mechanism]}"

    def get_listener_nodeport(self, auth_map: AuthMap) -> int:
        """Gets the current NodePort for the desired auth.protocol and auth.mechanism service."""
        service_name = self.build_listener_service_name(auth_map)
        if not (service := self.get_service(service_name)):
            raise Exception(
                f"Unable to find Service using {auth_map.protocol} and {auth_map.mechanism}"
            )

        return self.get_node_port(service, auth_map)

    def get_bootstrap_nodeport(self, auth_map: AuthMap) -> int:
        """Gets the current NodePort for the desired bootstrap auth.protocol and auth.mechanism service."""
        if not (service := self.get_service(self.bootstrap_service_name)):
            raise Exception("Unable to find bootstrap Service")

        return self.get_node_port(service, auth_map)

    def build_bootstrap_services(self) -> Service:
        """Builds a ClusterIP service for initial client connection."""
        pod = self.get_pod(self.pod_name)
        if not pod.metadata:
            raise Exception(f"Could not find metadata for {pod}")

        ports = []
        for (auth_protocol, auth_mechanism), port in SECURITY_PROTOCOL_PORTS.items():
            ports.append(
                ServicePort(
                    protocol="TCP",
                    port=port.external,
                    targetPort=port.external,
                    name=f"{auth_protocol.lower().replace('_', '-')}-{self.short_auth_mechanism_mapping[auth_mechanism]}-bootstrap-port",
                )
            )

        return Service(
            metadata=ObjectMeta(
                name=self.bootstrap_service_name,
                namespace=self.namespace,
                # owned by the StatefulSet
                ownerReferences=pod.metadata.ownerReferences,
            ),
            spec=ServiceSpec(
                externalTrafficPolicy="Local",
                type="NodePort",
                selector={"app.kubernetes.io/name": self.app_name},
                ports=ports,
            ),
        )

    def build_listener_service(self, auth_map: AuthMap) -> Service:
        """Builds a NodePort service for individual brokers and auth.protocols + auth.mechanisms.

        In order to discover all Kafka brokers, a client application must know the location of at least 1
        active broker, `bootstrap-server`. From there, the broker returns the `advertised.listeners`
        to the client application, here specified as <NODE-IP>:<NODE-PORT>.

        K8s-external requests hit <NODE-IP>:<NODE-PORT>, and are redirected to the corresponding
        statefulset.kubernetes.io/pod-name from the selector, and port matching the auth mechanism.

        If a pod was rescheduled to a new node, the node-ip defined in the `advertised.listeners`
        will be updated during the normal charm `config-changed` reconciliation.
        """
        pod = self.get_pod(pod_name=self.pod_name)
        if not pod.metadata:
            raise Exception(f"Could not find metadata for {pod}")

        service_name = self.build_listener_service_name(auth_map)
        svc_port = SECURITY_PROTOCOL_PORTS[auth_map].external

        return Service(
            metadata=ObjectMeta(
                name=service_name,
                namespace=self.namespace,
                ownerReferences=[
                    OwnerReference(
                        apiVersion=pod.apiVersion,
                        kind=pod.kind,
                        name=self.pod_name,
                        uid=pod.metadata.uid,
                        blockOwnerDeletion=False,
                    )
                ],
            ),
            spec=ServiceSpec(
                externalTrafficPolicy="Local",
                type="NodePort",
                selector={"statefulset.kubernetes.io/pod-name": self.pod_name},
                ports=[
                    ServicePort(
                        protocol="TCP",
                        port=svc_port,
                        targetPort=svc_port,
                        name=f"{service_name}-port",
                    ),
                ],
            ),
        )

    def apply_service(self, service: Service) -> None:
        """Applies a given Service."""
        try:
            self.client.apply(service)
        except ApiError as e:
            if e.status.code == 403:
                logger.error("Could not apply service, application needs `juju trust`")
                return
            if e.status.code == 422 and "port is already allocated" in e.status.message:
                logger.error(e.status.message)
                return
            else:
                raise

    # PRIVATE METHODS

    @cache
    def _get_pod(self, pod_name: str = "", *_) -> Pod:
        # Allows us to get pods from other peer units
        pod_name = pod_name or self.pod_name

        return self.client.get(
            res=Pod,
            name=pod_name,
        )

    @cache
    def _get_node(self, pod_name: str, *_) -> Node:
        pod = self.get_pod(pod_name)
        if not pod.spec or not pod.spec.nodeName:
            raise Exception("Could not find podSpec or nodeName")

        return self.client.get(
            Node,
            name=pod.spec.nodeName,
        )

    @cache
    def _get_node_ip(self, pod_name: str, *_) -> str:
        # all these redundant checks are because Lightkube's typing is awful
        node = self.get_node(pod_name)
        if not node.status or not node.status.addresses:
            raise Exception(f"No status found for {node}")

        for addresses in node.status.addresses:
            if addresses.type in ["ExternalIP", "InternalIP", "Hostname"]:
                return addresses.address

        return ""

    @cache
    def _get_service(self, service_name: str, *_) -> Service | None:
        return self.client.get(
            res=Service,
            name=service_name,
        )
