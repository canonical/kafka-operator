#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of state objects for the Kafka relations, apps and units."""

import json
import logging
import socket
from dataclasses import dataclass
from functools import cached_property
from typing import Annotated, MutableMapping, TypeAlias, TypedDict

import requests
from charms.data_platform_libs.v0.data_interfaces import (
    PROV_SECRET_PREFIX,
    SECRET_GROUPS,
    Data,
    ProviderData,
    RequirerData,
)
from charms.data_platform_libs.v1.data_interfaces import (
    SECRET_PREFIX,
    BaseModel,
    EntityPermissionModel,
    KafkaRequestModel,
    KafkaResponseModel,
    OpsPeerRepository,
    OpsRelationRepository,
    OptionalSecrets,
    OptionalSecretStr,
    SecretGroup,
    SecretNotFoundError,
    TlsSecretBool,
    TlsSecretStr,
)
from lightkube.resources.core_v1 import Node, Pod
from ops.model import Application, Model, ModelError, Relation, Unit
from pydantic import Field, ValidationError, field_validator

from literals import (
    BALANCER,
    BROKER,
    CONTROLLER,
    INTERNAL_USERS,
    KRAFT_NODE_ID_OFFSET,
    SECRETS_APP,
    SECRETS_UNIT,
    SECURITY_PROTOCOL_PORTS,
    TLS_RELATION,
    AuthMap,
    Substrates,
    TLSScope,
)
from managers.k8s import K8sManager

logger = logging.getLogger(__name__)

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


CPU = TypedDict("CPU", {"num.cores": str})
Capacity = TypedDict("Capacity", {"DISK": dict[str, str], "CPU": CPU, "NW_IN": str, "NW_OUT": str})
BrokerCapacity = TypedDict("BrokerCapacity", {"brokerId": str, "capacity": Capacity, "doc": str})
BrokerCapacities = TypedDict(
    "BrokerCapacities", {"brokerCapacities": list[BrokerCapacity]}, total=False
)

custom_secret_groups = SECRET_GROUPS
setattr(custom_secret_groups, "BROKER", "broker")
setattr(custom_secret_groups, "BALANCER", "balancer")
setattr(custom_secret_groups, "CONTROLLER", "controller")

SECRET_LABEL_MAP = {
    "broker-username": getattr(custom_secret_groups, "BROKER"),
    "broker-password": getattr(custom_secret_groups, "BROKER"),
    "controller-password": getattr(custom_secret_groups, "CONTROLLER"),
    "broker-uris": getattr(custom_secret_groups, "BROKER"),
    "balancer-username": getattr(custom_secret_groups, "BALANCER"),
    "balancer-password": getattr(custom_secret_groups, "BALANCER"),
    "balancer-uris": getattr(custom_secret_groups, "BALANCER"),
}

BrokerGroupSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "broker"]
ControllerGroupSecretStr = Annotated[
    OptionalSecretStr, Field(exclude=True, default=None), "controller"
]
BalancerGroupSecretStr = Annotated[
    OptionalSecretStr, Field(exclude=True, default=None), "balancer"
]


@dataclass
class GeneratedCa:
    """Data class to model generated CA artifacts."""

    ca: str
    ca_key: str


@dataclass
class SelfSignedCertificate:
    """Data class to model self signed certificate artifacts."""

    ca: str
    csr: str
    certificate: str
    private_key: str


RESOURCE_TYPES = {"TOPIC", "GROUP"}
VALID_OPERATIONS = {"READ", "WRITE", "CREATE", "DELETE", "DESCRIBE"}


class KafkaPermissionModel(EntityPermissionModel):
    """Extended permission request model for Kafka clients."""

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, v: str) -> str:
        """Checks if resource_type is valid and converts it to uppercase."""
        if v.upper() not in {"TOPIC", "GROUP"}:
            raise ValueError(f"resource type should be in {RESOURCE_TYPES}")
        return v.upper()

    @field_validator("privileges")
    @classmethod
    def validate_privileges(cls, v: list) -> list[str]:
        """Checks if resource_type is valid and converts it to uppercase."""
        ops = []
        for op in v:
            if op not in VALID_OPERATIONS:
                raise ValueError(f"privilege should be in {VALID_OPERATIONS}")
            ops.append(op)
        return ops


class KafkaCompatibilityResponseModel(KafkaResponseModel):
    """Response model compatible with V0."""

    tls: TlsSecretBool | TlsSecretStr = Field(default=None)
    consumer_group_prefix: str | None = Field(default=None)


class RelationStateV1:
    """Relation state object based on Data Interfaces V1."""

    def __init__(
        self,
        relation: Relation | None,
        model: Model,
        component: Unit | Application,
        extra_secret_fields: list[str] = [],
        data_model: BaseModel | None = None,
        substrate: Substrates | None = None,
        is_peer_relation: bool = False,
    ):
        self.model = model
        if is_peer_relation:
            self.repository = OpsPeerRepository(self.model, relation, component)
        else:
            self.repository = OpsRelationRepository(self.model, relation, component)
        self.relation = relation
        self.component = component
        self.data_model = data_model
        self.substrate = substrate
        self.is_peer_relation = is_peer_relation
        self.secret_fields = set(self.secret_map)
        if extra_secret_fields:
            self.secret_fields |= set(extra_secret_fields)

    def is_secret_field(self, field: str) -> bool:
        """Determine if a field is secret or not, based on the relation data model."""
        if field in self.secret_fields:
            return True

        # Handle dynamic secret fields
        if self.is_peer_relation and field.startswith("relation-"):
            return True

        return False

    @cached_property
    def secret_map(self) -> dict[str, SecretGroup]:
        """Return a mapping of fields to associated secret groups."""
        if not self.data_model:
            return {}

        _map = {}
        for field, field_info in self.data_model.__pydantic_fields__.items():
            if field_info.annotation in OptionalSecrets and len(field_info.metadata) == 1:
                if secret_group := SecretGroup(field_info.metadata[0]):
                    _map[field] = secret_group

        return _map

    @property
    def relation_data(self) -> dict:
        """Return the data dictionary containing secret and non-secret fields, compatible with V0."""
        _data = self.repository.get_data() or {}

        for secret_group in set(self.secret_map.values()) | {SecretGroup("extra")}:
            if secret := self.repository.get_secret(secret_group, None):
                try:
                    secret_info = (
                        secret.meta.get_info()  # pyright: ignore[reportOptionalMemberAccess]
                    )
                    _data |= self.model.get_secret(id=secret_info.id).get_content(refresh=True)
                except (AttributeError, SecretNotFoundError, ValueError):
                    _data |= secret.get_content()

        secret_fields = [fld for fld in _data if fld.startswith(SECRET_PREFIX)]
        for secret_field in secret_fields:
            if secret := self.model.get_secret(id=_data[secret_field]):
                _data |= secret.get_content(refresh=True)

        return _data

    def update(self, items: dict[str, str]) -> None:
        """Writes to relation_data via repository."""
        delete_fields = [key for key in items if not items[key]]
        update_content = {k: items[k] for k in items if k not in delete_fields}

        for k, v in update_content.items():
            if self.is_secret_field(k):
                secret_group = self.secret_map.get(k, SecretGroup("extra"))
                self.repository.write_secret_field(k, v, secret_group)
            else:
                self.repository.write_field(k, v)

        for key in delete_fields:
            if self.is_secret_field(key):
                secret_group = self.secret_map.get(key, SecretGroup("extra"))
                self.repository.delete_secret_field(key, secret_group)
            else:
                self.repository.delete_field(key)

    @property
    def network_interface(self) -> str:
        """Returns the network interface name of the relation based on network bindings."""
        if not self.relation:
            return ""

        try:
            if binding := self.model.get_binding(self.relation):
                if interfaces := binding.network.interfaces:
                    return interfaces[0].name
        except ModelError as e:
            logger.error(f"Can't retrieve network binding data: {e}")
            pass

        return ""

    @property
    def ip(self) -> str:
        """Returns the IP of the unit on the relation based on network bindings."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)

        # use the network interface we're bound to.
        if self.network_interface:
            s.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.network_interface.encode("utf-8")
            )

        s.connect(("10.10.10.10", 1))
        ip = s.getsockname()[0]
        s.close()

        return ip


class RelationState:
    """Relation state object."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        component: Unit | Application | None,
        substrate: Substrates | None = None,
    ):
        self.relation = relation
        self.data_interface = data_interface
        self.model = data_interface._model
        self.component = (
            component  # FIXME: remove, and use _fetch_my_relation_data defaults wheren needed
        )
        self.substrate = substrate
        self.relation_data = (
            self.data_interface.as_dict(self.relation.id) if self.relation else {}
        )  # FIXME: mappingproxytype?

    def __bool__(self) -> bool:
        """Boolean evaluation based on the existence of self.relation."""
        try:
            return bool(self.relation)
        except AttributeError:
            return False

    def update(self, items: dict[str, str]) -> None:
        """Writes to relation_data."""
        delete_fields = [key for key in items if not items[key]]
        update_content = {k: items[k] for k in items if k not in delete_fields}

        self.relation_data.update(update_content)

        for field in delete_fields:
            del self.relation_data[field]

        if not self.relation:
            return

        secret_keys = set(update_content) & set(SECRET_LABEL_MAP)
        for key in secret_keys:
            self.data_interface._add_or_update_relation_secrets(
                self.relation, SECRET_LABEL_MAP[key], {key}, {key: update_content[key]}
            )

    @property
    def network_interface(self) -> str:
        """Returns the network interface name of the relation based on network bindings."""
        if not self.relation:
            return ""

        try:
            if binding := self.model.get_binding(self.relation):
                if interfaces := binding.network.interfaces:
                    return interfaces[0].name
        except ModelError as e:
            logger.error(f"Can't retrieve network binding data: {e}")
            pass

        return ""

    @property
    def ip(self) -> str:
        """Returns the IP of the unit on the relation based on network bindings."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)

        # use the network interface we're bound to.
        if self.network_interface:
            s.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.network_interface.encode("utf-8")
            )

        s.connect(("10.10.10.10", 1))
        ip = s.getsockname()[0]
        s.close()

        return ip


class PeerClusterOrchestratorData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = BROKER.requested_secrets

    # This is to bypass the PrematureDataAccessError, which is irrelevant in this case.
    def _update_relation_data(self, relation: Relation, data: dict[str, str]) -> None:
        """Set values for fields not caring whether it's a secret or not."""
        super(ProviderData, self)._update_relation_data(relation, data)


class PeerClusterData(ProviderData, RequirerData):
    """Broker provider data model."""

    SECRET_LABEL_MAP = SECRET_LABEL_MAP
    SECRET_FIELDS = list(set(BALANCER.requested_secrets) | set(CONTROLLER.requested_secrets))

    # This is to bypass the PrematureDataAccessError, which is irrelevant in this case.
    def _update_relation_data(self, relation: Relation, data: dict[str, str]) -> None:
        """Set values for fields not caring whether it's a secret or not."""
        super(ProviderData, self)._update_relation_data(relation, data)


class PeerCluster(RelationState):
    """State collection metadata for a peer-cluster application."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        broker_username: str = "",
        broker_password: str = "",
        broker_uris: str = "",
        cluster_uuid: str = "",
        bootstrap_controller: str = "",
        bootstrap_unit_id: str = "",
        bootstrap_replica_id: str = "",
        racks: int = 0,
        broker_capacities: BrokerCapacities = {},
        balancer_username: str = "",
        balancer_password: str = "",
        balancer_uris: str = "",
        controller_password: str = "",
    ):
        super().__init__(relation, data_interface, None, None)
        self._broker_username = broker_username
        self._broker_password = broker_password
        self._broker_uris = broker_uris
        self._cluster_uuid = cluster_uuid
        self._bootstrap_controller = bootstrap_controller
        self._bootstrap_unit_id = bootstrap_unit_id
        self._bootstrap_replica_id = bootstrap_replica_id
        self._racks = racks
        self._broker_capacities = broker_capacities
        self._balancer_username = balancer_username
        self._balancer_password = balancer_password
        self._balancer_uris = balancer_uris
        self._controller_password = controller_password

    def _fetch_from_secrets(self, group, field) -> str:
        if not self.relation:
            return ""

        if secrets_uri := self.relation.data[self.relation.app].get(
            f"{PROV_SECRET_PREFIX}{group}"
        ):
            if secret := self.data_interface._model.get_secret(id=secrets_uri):
                return secret.get_content(refresh=True).get(field, "")

        return ""

    @property
    def roles(self) -> str:
        """All the roles pass from the related application."""
        if not self.relation:
            return ""

        return (
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="roles")
            or ""
        )

    @property
    def broker_username(self) -> str:
        """The provided username for the broker application."""
        if self._broker_username:
            return self._broker_username

        if not self.relation or not self.relation.app:
            return ""

        return self._fetch_from_secrets("broker", "broker-username")

    @property
    def broker_password(self) -> str:
        """The provided password for the broker application."""
        if self._broker_password:
            return self._broker_password

        if not self.relation or not self.relation.app:
            return ""

        return self._fetch_from_secrets("broker", "broker-password")

    @property
    def broker_uris(self) -> str:
        """The provided uris for the balancer application to connect to the broker application."""
        if self._broker_uris:
            return self._broker_uris

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BALANCER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("broker-uris", "")

    @property
    def controller_password(self) -> str:
        """The controller user password in KRaft mode."""
        if self._controller_password:
            return self._controller_password

        if not self.relation or not self.relation.app:
            return ""

        return self._fetch_from_secrets("controller", "controller-password")

    @property
    def cluster_uuid(self) -> str:
        """The cluster uuid used to format storages in KRaft mode."""
        if self._cluster_uuid:
            return self._cluster_uuid

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="cluster-uuid"
            )
            or ""
        )

    @property
    def bootstrap_controller(self) -> str:
        """Bootstrap controller in KRaft mode."""
        if self._bootstrap_controller:
            return self._bootstrap_controller

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-controller"
            )
            or ""
        )

    @property
    def bootstrap_unit_id(self) -> str:
        """Bootstrap unit ID in KRaft mode."""
        if self._bootstrap_unit_id:
            return self._bootstrap_unit_id

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-unit-id"
            )
            or ""
        )

    @property
    def bootstrap_replica_id(self) -> str:
        """Directory ID of the bootstrap node in KRaft mode."""
        if self._bootstrap_replica_id:
            return self._bootstrap_replica_id

        if not self.relation or not self.relation.app:
            return ""

        return (
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="bootstrap-replica-id"
            )
            or ""
        )

    @property
    def racks(self) -> int:
        """The number of racks for the brokers."""
        if self._racks:
            return self._racks

        if not self.relation:
            return 0

        return int(
            self.data_interface.fetch_relation_field(relation_id=self.relation.id, field="racks")
            or 0
        )

    @property
    def broker_capacities(self) -> BrokerCapacities:
        """The capacities for all Kafka brokers."""
        if self._broker_capacities:
            return self._broker_capacities

        if not self.relation:
            return {}

        return json.loads(
            self.data_interface.fetch_relation_field(
                relation_id=self.relation.id, field="broker-capacities"
            )
            or "{}"
        )

    @property
    def balancer_username(self) -> str:
        """The provided username for the balancer application."""
        if self._balancer_username:
            return self._balancer_username

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-username", "")

    @property
    def balancer_password(self) -> str:
        """The provided password for the balancer application."""
        if self._balancer_password:
            return self._balancer_password

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-password", "")

    @property
    def balancer_uris(self) -> str:
        """The provided uris for the broker application to connect to the balancer application."""
        if self._balancer_uris:
            return self._balancer_uris

        if not self.relation or not self.relation.app:
            return ""

        return self.data_interface._fetch_relation_data_with_secrets(
            component=self.relation.app,
            req_secret_fields=BROKER.requested_secrets,
            relation=self.relation,
            fields=BALANCER.requested_secrets,
        ).get("balancer-uris", "")

    @property
    def broker_connected(self) -> bool:
        """Checks if there is an active broker relation with all necessary data."""
        # FIXME rename to specify balancer-broker connection
        if not all(
            [
                self.broker_username,
                self.broker_password,
                self.broker_uris,
                self.broker_capacities,
                # rack is optional, empty if not rack-aware
            ]
        ):
            return False

        return True

    @property
    def broker_connected_kraft_mode(self) -> bool:
        """Checks for necessary data required by a controller."""
        if not all([self.broker_username, self.broker_password, self.cluster_uuid]):
            return False

        return True

    @property
    def super_users(self) -> str:
        """Returns the super users defined on the cluster."""
        if not self.relation or not self.relation.app:
            return ""

        return self.relation_data.get("super-users", "")


class KafkaCluster(RelationStateV1):
    """State collection metadata for the peer relation."""

    def __init__(
        self,
        relation: Relation | None,
        model: Model,
        component: Application,
        network_bandwidth: int = 50000,
    ):
        super().__init__(
            relation,
            model,
            component,
            substrate=None,
            extra_secret_fields=SECRETS_APP,
            is_peer_relation=True,
        )
        self.app = component
        self.network_bandwidth = network_bandwidth

    @property
    def internal_user_credentials(self) -> dict[str, str]:
        """The charm internal usernames and passwords, e.g `sync` and `admin`.

        Returns:
            Dict of usernames and passwords
        """
        credentials = {
            user: password
            for user in INTERNAL_USERS
            if (password := self.relation_data.get(f"{user}-password"))
        }

        if not len(credentials) == len(INTERNAL_USERS):
            return {}

        return credentials

    @property
    def controller_password(self) -> str:
        """The controller user password in KRaft mode."""
        return self.relation_data.get("controller-password", "")

    @property
    def client_passwords(self) -> dict[str, str]:
        """Usernames and passwords of related client applications."""
        return {key: value for key, value in self.relation_data.items() if "relation-" in key}

    # --- TLS ---

    @property
    def tls_enabled(self) -> bool:
        """Flag to check if the cluster should run with TLS.

        Returns:
            True if TLS encryption should be active. Otherwise False
        """
        relation = self.model.get_relation(TLS_RELATION)

        if not relation or not relation.active:
            return False

        return True

    @property
    def balancer_username(self) -> str:
        """Persisted balancer username."""
        return self.relation_data.get("balancer-username", "")

    @property
    def balancer_password(self) -> str:
        """Persisted balancer password."""
        return self.relation_data.get("balancer-password", "")

    @property
    def balancer_uris(self) -> str:
        """Persisted balancer uris."""
        return self.relation_data.get("balancer-uris", "")

    @property
    def cluster_uuid(self) -> str:
        """Cluster uuid used for initializing storages."""
        return self.relation_data.get("cluster-uuid", "")

    @property
    def bootstrap_replica_id(self) -> str:
        """Directory ID of the bootstrap controller."""
        return self.relation_data.get("bootstrap-replica-id", "")

    @property
    def bootstrap_controller(self) -> str:
        """HOST:PORT address of the bootstrap controller."""
        return self.relation_data.get("bootstrap-controller", "")

    @property
    def bootstrap_unit_id(self) -> str:
        """Unit ID of the bootstrap controller."""
        return self.relation_data.get("bootstrap-unit-id", "")

    @property
    def broker_capacities_snapshot(self) -> dict[int, dict]:
        """Snapshot of broker capacities."""
        raw = self.relation_data.get("broker-capacities-snapshot") or {}
        # JSON keys can't be int, so convert them back to int here,
        # as we always treat broker_id as int.
        return {int(k): v for k, v in raw.items()}

    def add_broker(self, broker) -> None:
        """Add a given `KafkaBroker` to the broker capacities snapshot."""
        if not all([broker.cores, broker.storages]):
            return

        snapshot = self.broker_capacities_snapshot

        updated = {
            "DISK": broker.storages,
            "CPU": {"num.cores": broker.cores},
            "NW_IN": str(self.network_bandwidth),
            "NW_OUT": str(self.network_bandwidth),
        }
        current = snapshot.get(broker.broker_id, {})

        if updated == current:
            return

        snapshot[broker.broker_id] = dict(updated)
        self.update({"broker-capacities-snapshot": json.dumps(snapshot)})

    def remove_broker(self, broker_id: int) -> None:
        """Remove a broker ID from the broker capacities snapshot."""
        snapshot = dict(self.broker_capacities_snapshot)

        if broker_id not in snapshot:
            return

        snapshot.pop(broker_id)
        self.update({"broker-capacities-snapshot": json.dumps(snapshot)})


class TLSState:
    """State collection metadata for TLS credentials."""

    def __init__(self, relation_state: RelationStateV1, scope: TLSScope):
        self.scope = scope
        self.relation_state = relation_state
        self.relation_data = relation_state.relation_data

    @property
    def private_key(self) -> str:
        """The unit private-key set during `certificates_joined`.

        Returns:
            String of key contents
            Empty if key not yet generated
        """
        return self.relation_data.get(f"{self.scope.value}-private-key", "")

    @private_key.setter
    def private_key(self, value: str) -> None:
        self.relation_state.update({f"{self.scope.value}-private-key": value})

    @property
    def csr(self) -> str:
        """The unit cert signing request.

        Returns:
            String of csr contents
            Empty if csr not yet generated
        """
        return self.relation_data.get(f"{self.scope.value}-csr", "")

    @csr.setter
    def csr(self, value: str) -> None:
        self.relation_state.update({f"{self.scope.value}-csr": value})

    @property
    def certificate(self) -> str:
        """The signed unit certificate from the provider relation.

        Returns:
            String of cert contents in PEM format
            Empty if cert not yet generated/signed
        """
        return self.relation_data.get(f"{self.scope.value}-certificate", "")

    @certificate.setter
    def certificate(self, value: str) -> None:
        self.relation_state.update({f"{self.scope.value}-certificate": value})

    @property
    def ca(self) -> str:
        """The ca used to sign unit cert.

        Returns:
            String of ca contents in PEM format
            Empty if cert not yet generated/signed
        """
        return self.relation_data.get(f"{self.scope.value}-ca-cert", "")

    @ca.setter
    def ca(self, value: str) -> None:
        self.relation_state.update({f"{self.scope.value}-ca-cert": value})

    @property
    def chain(self) -> list[str]:
        """The chain used to sign unit cert."""
        # DI v1 does handle the JSON serialization
        raw = self.relation_state.relation_data.get(f"{self.scope.value}-chain")

        if not raw:
            return []

        if isinstance(raw, list):
            return raw

        return json.loads(raw)

    @chain.setter
    def chain(self, value: str) -> None:
        self.relation_state.update({f"{self.scope.value}-chain": value})

    @property
    def bundle(self) -> list[str]:
        """The cert bundle used for TLS identity."""
        if not all([self.certificate, self.ca]):
            return []

        # manual-tls-certificates is loaded with the signed cert, the intermediate CA that signed it
        # and then the missing chain for that CA
        bundle = [self.certificate, self.ca] + self.chain
        return sorted(set(bundle), key=bundle.index)  # ordering might matter

    @property
    def rotate(self) -> bool:
        """Whether or not CA/chain rotation is in progress."""
        return bool(self.relation_data.get(f"{self.scope.value}-rotation", ""))

    @rotate.setter
    def rotate(self, value: bool) -> None:
        _value = "" if not value else "true"
        self.relation_state.update({f"{self.scope.value}-rotation": _value})

    @property
    def trusted_certificates(self) -> set[str]:
        """Returns a list of certificate fingeprints loaded into this unit's truststore."""
        trust_list = self.relation_data.get(f"{self.scope.value}-trust") or []
        return set(trust_list)

    @trusted_certificates.setter
    def trusted_certificates(self, value: str | list[str]) -> None:
        _value = [value] if isinstance(value, str) else value

        if set(_value) == self.trusted_certificates:
            return

        _value.sort()
        _value = json.dumps(_value)

        self.relation_state.update({f"{self.scope.value}-trust": _value})

    @property
    def ready(self) -> bool:
        """Returns True if all the necessary TLS relation data has been set, False otherwise."""
        return all([self.certificate, self.ca, self.private_key])

    def set_self_signed(self, value: SelfSignedCertificate) -> None:
        """Sets CA, private_key, CSR, and cert state vars based on the provided `SelfSignedCertificate` bundle."""
        self.private_key = value.private_key
        self.certificate = value.certificate
        self.ca = value.ca
        self.csr = value.csr


class KafkaBroker(RelationStateV1):
    """State collection metadata for a unit."""

    def __init__(
        self,
        relation: Relation | None,
        model: Model,
        component: Unit,
        substrate: Substrates,
    ):
        super().__init__(
            relation,
            model,
            component,
            substrate=substrate,
            extra_secret_fields=SECRETS_UNIT,
            is_peer_relation=True,
        )
        self.unit = component
        self.k8s = K8sManager(
            pod_name=self.pod_name,
            namespace=self.unit._backend.model_name,
        )

    @property
    def unit_id(self) -> int:
        """The id of the unit from the unit name.

        e.g kafka/2 --> 2
        """
        return int(self.unit.name.split("/")[1])

    @property
    def broker_id(self) -> int:
        """`node.id` of the `broker` in KRaft."""
        return KRAFT_NODE_ID_OFFSET + self.unit_id

    @property
    def internal_address(self) -> str:
        """The address for internal communication between brokers."""
        addr = ""
        if self.substrate == "vm":
            for key in ["hostname", "ip", "private-address"]:
                if addr := self.relation_data.get(key, ""):
                    break

        if self.substrate == "k8s":
            addr = f"{self.unit.name.split('/')[0]}-{self.unit_id}.{self.unit.name.split('/')[0]}-endpoints"

        return addr

    @property
    def peer_ip_address(self) -> str:
        """The IP address of the unit on the peer relation."""
        return self.relation_data.get("ip", "")

    @peer_ip_address.setter
    def peer_ip_address(self, value: str) -> None:
        return self.update({"ip": value})

    def update_peer_ip_address(self) -> None:
        """Update unit's peer IP address."""
        self.peer_ip_address = self.ip or self.internal_address

    def relation_ip_address(self, relation: Relation | None) -> str:
        """Return the IP address for a given relation."""
        if not relation:
            return ""

        if self.substrate == "k8s":
            return self.internal_address

        return self.relation_data.get(f"ip-{relation.id}", "")

    def update_relation_ip_address(self, relation: Relation, ip_address: str) -> None:
        """Update the IP address for a given relation."""
        if not relation:
            return

        self.update({f"ip-{relation.id}": ip_address})

    # --- TLS ---
    @property
    def peer_certs(self) -> TLSState:
        """TLS state for internal (peer) communications."""
        return TLSState(self, TLSScope.PEER)

    @property
    def client_certs(self) -> TLSState:
        """TLS state for external (client) communications."""
        return TLSState(self, TLSScope.CLIENT)

    @property
    def keystore_password(self) -> str:
        """The unit keystore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("keystore-password", "")

    @property
    def truststore_password(self) -> str:
        """The unit truststore password set during `certificates_joined`.

        Returns:
            String of password
            None if password not yet generated
        """
        return self.relation_data.get("truststore-password", "")

    @property
    def storages(self) -> JSON:
        """The current Juju storages for the unit."""
        # DI v1 does handle the JSON serialization
        return self.relation_data.get("storages") or {}

    @property
    def cores(self) -> str:
        """The number of CPU cores for the unit machine."""
        return str(self.relation_data.get("cores", ""))

    @property
    def rack(self) -> str:
        """The rack for the broker on broker.rack from rack.properties."""
        return self.relation_data.get("rack", "")

    @property
    def pod_name(self) -> str:
        """The name of the K8s Pod for the unit.

        K8s-only.
        """
        return self.unit.name.replace("/", "-")

    @cached_property
    def pod(self) -> Pod:
        """The Pod of the unit.

        K8s-only.
        """
        return self.k8s.get_pod(self.pod_name)

    @cached_property
    def node(self) -> Node:
        """The Node the unit is scheduled on.

        K8s-only.
        """
        return self.k8s.get_node(self.pod_name)

    @cached_property
    def node_ip(self) -> str:
        """The IPV4/IPV6 IP address the Node the unit is on.

        K8s-only.
        """
        return self.k8s.get_node_ip(self.pod_name)

    @property
    def metadata_directory_id(self) -> str:
        """Directory ID of the node as saved in `meta.properties`."""
        return self.relation_data.get("metadata-directory-id", "")

    @property
    def added_to_quorum(self) -> bool:
        """Whether or not this node is added to dynamic quorum in KRaft mode."""
        return bool(self.relation_data.get("added-to-quorum", False))


class KafkaClient(RelationStateV1):
    """State collection metadata for a single related client application."""

    def __init__(
        self,
        relation: Relation | None,
        model: Model,
        component: Application,
        request: KafkaRequestModel,
        local_app: Application | None = None,
        bootstrap_server: str = "",
        password: str = "",  # nosec: B107
        tls: str = "",
    ):
        super().__init__(
            relation,
            model,
            component,
            substrate=None,
        )
        self.app = component
        self._local_app = local_app
        self._bootstrap_server = bootstrap_server
        self._password = password
        self._tls = tls
        self.request = request
        self.request_id = request.request_id

    @property
    def username(self) -> str:
        """The generated username for the client application."""
        if not self.relation:
            return ""

        return self.generate_username(self.relation.id, self.request_id)

    @property
    def bootstrap_server(self) -> str:
        """The Kafka server endpoints for the client application to connect with."""
        if not all([self.tls, self.mtls_cert]):
            return self._bootstrap_server

        scram_ssl_auth = AuthMap("SASL_SSL", "SCRAM-SHA-512")
        mtls_auth = AuthMap("SSL", "SSL")

        return self._bootstrap_server.replace(
            f":{SECURITY_PROTOCOL_PORTS[scram_ssl_auth].client}",
            f":{SECURITY_PROTOCOL_PORTS[mtls_auth].client}",
        )

    @property
    def password(self) -> str:
        """The generated password for the client application."""
        return self._password

    @property
    def consumer_group_prefix(self) -> str:
        """The assigned consumer group prefix for a client application presenting consumer role."""
        return self.relation_data.get(
            "consumer-group-prefix",
            f"{self.username}-" if "consumer" in self.extra_user_roles else "",
        )

    @property
    def tls(self) -> str:
        """Flag to confirm whether or not TLS is enabled.

        Returns:
            String of either 'enabled' or 'disabled'
        """
        return self._tls

    @property
    def topic(self) -> str:
        """The requested topic for the client."""
        return self.request.resource

    @property
    def extra_user_roles(self) -> str:
        """The client defined roles for their application.

        Can be any comma-delimited selection of `producer`, `consumer` and `admin`.
        When `admin` is set, the Kafka charm interprets this as a new super.user.
        """
        return self.request.extra_user_roles or ""

    @property
    def mtls_cert(self) -> str:
        """Returns TLS cert of the client."""
        if not self.request.mtls_cert:
            return ""

        return self.request.mtls_cert

    @property
    def alias(self) -> str:
        """The alias used to refer to client's MTLS certificate."""
        if not self.relation:
            return ""

        return self.generate_alias(self.relation.app.name, self.relation.id)

    @property
    def version(self) -> str:
        """The Data Interface version of the client."""
        return self.relation_data.get("version", "v0")

    @property
    def written_data(self) -> dict:
        """The data written for this client."""
        if not self._local_app:
            return {}

        _data = RelationStateV1(self.relation, self.model, self._local_app).relation_data
        if self.version == "v0":
            return _data

        if "requests" not in _data:
            return {}

        # Since DI v1 relations could include multiple requests, we need to extract
        # data for this specific request, both from relation data and secrets.
        my_data = [r for r in _data["requests"] if r.get("request-id") == self.request_id]
        if not my_data:
            return {}

        _data = my_data[0]
        secret_fields = [fld for fld in _data if fld.startswith(SECRET_PREFIX)]
        for secret_field in secret_fields:
            if secret_uri := _data[secret_field]:
                if secret := self.model.get_secret(id=secret_uri):
                    _data |= secret.get_content(refresh=True)

        return _data

    def needs_update(self, broker_ca: str) -> bool:
        """Check if written data for this client needs update, based on current Kafka app state."""
        state = self.written_data
        return not all(
            [
                self.username == state.get("username"),
                self.password == state.get("password"),
                self.bootstrap_server == state.get("endpoints"),
                self.tls == state.get("tls"),
                broker_ca == state.get("tls-ca"),
            ]
        )

    @property
    def secret_user(self) -> str | None:
        """The ID of the secret containing auth information, aka 'secret-user'."""
        if secret_user := self.repository.get_secret(SecretGroup("user"), None, self.request_id):
            if secret_info := secret_user.get_info():
                return secret_info.id

        return None

    @property
    def secret_tls(self) -> str | None:
        """The ID of the secret containing tls information, aka 'secret-tls'."""
        if secret_tls := self.repository.get_secret(SecretGroup("tls"), None, self.request_id):
            if secret_info := secret_tls.get_info():
                return secret_info.id

        return None

    @property
    def permissions(self) -> list[KafkaPermissionModel]:
        """List of permissions requested by the client."""
        if not self.request.entity_permissions:
            return []

        try:
            return [KafkaPermissionModel(**p.dict()) for p in self.request.entity_permissions]
        except ValidationError as e:
            # TODO: propagate the error to the client once DI V1 supports DA-174.
            logger.error(f"Permissions requested by the client is invalid: {e}")
            return []

    @staticmethod
    def generate_username(relation_id: int, request_id: str | None) -> str:
        """Generate the username for a specific request on a relation."""
        postfix = f"-{request_id}" if request_id else ""
        return f"relation-{relation_id}{postfix}"

    @staticmethod
    def generate_alias(app_name: str, relation_id: int) -> str:
        """Generate an alias from a relation."""
        return f"{app_name}-{relation_id}"


class OAuth:
    """State collection metadata for the oauth relation."""

    def __init__(self, relation: Relation | None):
        self.relation = relation

    @property
    def relation_data(self) -> MutableMapping[str, str]:
        """Oauth relation data object."""
        if not self.relation or not self.relation.app:
            return {}

        return self.relation.data[self.relation.app]

    @property
    def issuer_url(self) -> str:
        """The issuer URL to identify the IDP."""
        return self.relation_data.get("issuer_url", "")

    @property
    def jwks_endpoint(self) -> str:
        """The JWKS endpoint needed to validate JWT tokens."""
        return self.relation_data.get("jwks_endpoint", "")

    @property
    def introspection_endpoint(self) -> str:
        """The introspection endpoint needed to validate non-JWT tokens."""
        return self.relation_data.get("introspection_endpoint", "")

    @property
    def jwt_access_token(self) -> bool:
        """A flag indicating if the access token is JWT or not."""
        return self.relation_data.get("jwt_access_token", "false").lower() == "true"

    @property
    def uses_trusted_ca(self) -> bool:
        """A flag indicating if the IDP uses certificates signed by a trusted CA."""
        try:
            requests.get(self.issuer_url, timeout=10)
            return True
        except requests.exceptions.SSLError:
            return False
        except requests.exceptions.RequestException:
            return True
