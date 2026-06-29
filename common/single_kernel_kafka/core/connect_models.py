#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Collection of context objects for the Kafka Connect charm relations, apps and units."""

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, cast

from charms.data_platform_libs.v0.data_interfaces import (
    Data,
    DataPeerData,
    DataPeerOtherUnitData,
    DataPeerUnitData,
    KafkaConnectProviderData,
    KafkaRequirerData,
    ProviderData,
    RequirerData,
)
from charms.data_platform_libs.v0.data_models import TypedCharmBase
from ops import Object
from ops.model import Application, Relation, RelationDataAccessError, Unit
from typing_extensions import override

from .literals import SUBSTRATE, ConnectLiterals, ConnectStatus, Substrates, TLSScope
from .models import TLSContextBase, TLSManagerSettings
from .structured_config import ConnectCharmConfig

if TYPE_CHECKING:
    from charms.rolling_ops.v0.rollingops import RollingOpsManager

    from ..managers.auth import ConnectAuthManager
    from ..managers.connect import ConnectManager
    from ..managers.tls import TLSManager
    from ..workload import ConnectWorkloadK8s, ConnectWorkloadMachine


class ConnectCharmBase(TypedCharmBase[ConnectCharmConfig], ABC):
    """Base model for Kafka operators."""

    config_type = ConnectCharmConfig
    container_name = "kafka-connect"

    auth_manager: "ConnectAuthManager"
    connect_manager: "ConnectManager"
    context: "ConnectContext"
    pending_inactive_statuses: list[ConnectStatus]
    restart: "RollingOpsManager"
    substrate: Substrates
    tls_manager: "TLSManager"
    workload: "ConnectWorkloadMachine | ConnectWorkloadK8s"

    @abstractmethod
    def _set_status(self, key: ConnectStatus) -> None: ...

    @abstractmethod
    def reconcile(self) -> None:
        """Substrate-agnostic method for startup/restarts/config-changes which orchestrates workload, managers and handlers.

        This method is safe to call and only triggers a workload restart if necessary.
        """
        ...


class WithStatus(ABC):
    """Abstract base mixin class for objects with status."""

    @property
    @abstractmethod
    def status(self) -> ConnectStatus:
        """Returns status of the object."""
        ...

    @property
    def ready(self) -> bool:
        """Returns True if the status is Active and False otherwise."""
        if self.status == ConnectStatus.ACTIVE:
            return True

        return False


class RelationContext(WithStatus):
    """Relation context object."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: Data,
        component: Unit | Application | None,
        substrate: Substrates = cast(Substrates, SUBSTRATE),
    ):
        self.relation = relation
        self.data_interface = data_interface
        self.component = component
        self.substrate = substrate
        self.relation_data = self.data_interface.as_dict(self.relation.id) if self.relation else {}

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

    def _fetch_from_secrets(self, field) -> str:
        """Fetches a field from secrets defined at the remote unit of the relation."""
        if not self.relation or not self.relation.units:
            return ""

        remote_unit = next(iter(self.relation.units))

        try:
            return self.data_interface._fetch_relation_data_with_secrets(
                remote_unit, [field], self.relation
            ).get(field, "")
        except RelationDataAccessError:
            # remote unit has not the secrets yet.
            pass

        return ""

    @property
    def tls_enabled(self) -> bool:
        """Returns True if TLS is enabled on relation."""
        if not self.relation:
            return False

        tls = self.relation_data.get("tls")

        if tls is not None and tls != "disabled":
            return True

        return False


class KafkaClientContext(RelationContext):
    """Context collection metadata for kafka-client relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: RequirerData,
    ):
        super().__init__(relation, data_interface, None)

    @property
    def username(self) -> str:
        """Returns the Kafka client username."""
        if not self.relation:
            return ""

        return self.relation_data.get("username", "")

    @property
    def password(self) -> str:
        """Returns the Kafka client password."""
        if not self.relation:
            return ""

        return self.relation_data.get("password", "")

    @property
    def bootstrap_servers(self) -> str:
        """Returns Kafka bootstrap servers."""
        if not self.relation:
            return ""

        return self.relation_data.get("endpoints", "")

    @property
    def broker_ca(self) -> str:
        """Returns the broker CA if the relation uses TLS, otherwise empty string."""
        if not self.relation or not self.tls_enabled:
            return ""

        return self.relation_data.get("tls-ca", "")

    @property
    def security_protocol(self) -> str:
        """Returns the security protocol."""
        return "SASL_PLAINTEXT" if not self.tls_enabled else "SASL_SSL"

    @property
    def security_mechanism(self) -> str:
        """Returns the security mechanism in use."""
        return ConnectLiterals.DEFAULT_SECURITY_MECHANISM

    @property
    @override
    def status(self) -> ConnectStatus:
        if not self.relation:
            return ConnectStatus.MISSING_KAFKA

        if not all([self.username, self.password, self.bootstrap_servers]):
            return ConnectStatus.NO_KAFKA_CREDENTIALS

        return ConnectStatus.ACTIVE


class ConnectClientContext(RelationContext):
    """Context collection metadata for kafka-client relation."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: ProviderData,
    ):
        super().__init__(relation, data_interface, None)

    @property
    def plugin_url(self) -> str:
        """Returns the client's plugin-url REST endpoint."""
        if not self.relation:
            return ""

        return self.relation_data.get("plugin-url", "")

    @property
    def endpoints(self) -> str:
        """Returns Kafka Connect endpoints set for the client."""
        if not self.relation:
            return ""

        return self.relation_data.get("endpoints", "")

    @property
    def username(self) -> str:
        """Returns the Kafka Connect client username."""
        if not self.relation:
            return ""

        return f"relation-{self.relation.id}"

    @property
    def password(self) -> str:
        """Returns the Kafka Connect client password."""
        if not self.relation:
            return ""

        return self._fetch_from_secrets("password")

    @property
    @override
    def status(self) -> ConnectStatus:
        return ConnectStatus.ACTIVE


class TLSContext(RelationContext, TLSContextBase):
    """TLS metadata of a relation."""

    CA = "ca"
    CHAIN = "chain"
    CERT = "certificate"
    CSR = "csr"
    BROKER_CA = "broker"
    PRIVATE_KEY = "private-key"
    KEYSTORE_PASSWORD = "keystore-password"
    TRUSTSTORE_PASSWORD = "truststore-password"
    KEYS = {CA, CERT, CSR, CHAIN}
    SECRETS = [CERT, CSR, PRIVATE_KEY, KEYSTORE_PASSWORD, TRUSTSTORE_PASSWORD]

    def __init__(self, relation, data_interface, component, substrate=SUBSTRATE):
        super().__init__(relation, data_interface, component, substrate)

    @property
    def private_key(self) -> str:
        """Private key of the TLS relation."""
        return self.relation_data.get(self.PRIVATE_KEY, "")

    @property
    def csr(self) -> str:
        """Certificate Signing Request (CSR) of the TLS relation."""
        return self.relation_data.get(self.CSR, "")

    @property
    def certificate(self) -> str:
        """The signed certificate from the provider relation."""
        return self.relation_data.get(self.CERT, "")

    @property
    def ca(self) -> str:
        """The CA used to sign the certificate."""
        return self.relation_data.get(self.CA, "")

    @property
    def chain(self) -> list[str]:
        """The chain used to sign unit cert."""
        full_chain = json.loads(self.relation_data.get(self.CHAIN, "null")) or []
        # to avoid adding certificate to truststore if self-signed
        clean_chain: set[str] = set(full_chain) - {self.certificate, self.ca}

        return list(clean_chain)

    @property
    def bundle(self) -> list[str]:
        """The cert bundle used for TLS identity."""
        if not all([self.certificate, self.ca]):
            return []

        # manual-tls-certificates is loaded with the signed cert, the intermediate CA that signed it
        # and then the missing chain for that CA
        # We need to present the full bundle - aka Keystore
        # we need to trust each item in the bundle - aka Truststore
        bundle = [self.certificate, self.ca] + self.chain
        return sorted(set(bundle), key=bundle.index)  # ordering might matter

    @property
    def keystore_password(self) -> str:
        """The keystore password."""
        return self.relation_data.get(self.KEYSTORE_PASSWORD, "")

    @property
    def truststore_password(self) -> str:
        """The truststore password."""
        return self.relation_data.get(self.TRUSTSTORE_PASSWORD, "")

    @property
    @override
    def status(self) -> ConnectStatus:
        return ConnectStatus.ACTIVE


class WorkerUnitContext(RelationContext):
    """Context collection metadata for a single Kafka Connect worker unit."""

    def __init__(
        self,
        relation: Relation | None,
        data_interface: DataPeerUnitData,
        component: Unit,
    ):
        super().__init__(relation, data_interface, component)
        self.data_interface = data_interface
        self.unit = component

    @property
    def unit_id(self) -> int:
        """The id of the unit from the unit name."""
        return int(self.unit.name.split("/")[1])

    @property
    def tls(self) -> TLSContext:
        """TLS Context of the worker unit."""
        return TLSContext(self.relation, self.data_interface, self.component)

    @property
    def internal_address(self) -> str:
        """The IPv4 address or FQDN of the worker unit."""
        addr = ""
        if self.substrate == "vm":
            for key in ["hostname", "ip", "private-address"]:
                if addr := self.relation_data.get(key, ""):
                    break

        if self.substrate == "k8s":
            addr = f"{self.unit.name.split('/')[0]}-{self.unit_id}.{self.unit.name.split('/')[0]}-endpoints"

        return addr

    @property
    def should_restart(self) -> bool:
        """Determines whether a restart of service is required or not."""
        if not self.relation:
            return False

        return self.relation_data.get("restart", False) == "true"

    @should_restart.setter
    def should_restart(self, value: bool) -> None:
        _val = "true" if value else "false"
        self.update({"restart": _val})

    @property
    @override
    def status(self) -> ConnectStatus:
        return ConnectStatus.ACTIVE

    def get_rest_endpoint(
        self, protocol: str = "http", port: int = ConnectLiterals.DEFAULT_API_PORT
    ) -> str:
        """Returns the REST endpoint of the unit.

        Args:
            protocol (str, optional): REST protocol. Defaults to "http".
            port (int, optional): REST port. Defaults to DEFAULT_API_PORT.
        """
        return f"{protocol}://{self.internal_address}:{port}"


class PeerWorkersContext(RelationContext):
    """Context collection metadata for Kafka Connect peer relation."""

    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "admin-password"

    def __init__(self, relation, data_interface):
        super().__init__(relation, data_interface, None)

    @property
    def admin_password(self) -> str:
        """Internal admin user's password."""
        if not self.relation:
            return ""

        return self.relation_data.get(self.ADMIN_PASSWORD, "")

    @property
    @override
    def status(self) -> ConnectStatus:
        return ConnectStatus.ACTIVE


class ConnectContext(WithStatus, Object):
    """Context model for the Kafka Connect charm."""

    def __init__(self, charm: "ConnectCharmBase", substrate: Substrates):
        super().__init__(parent=charm, key="charm_context")
        self.substrate = substrate
        self.config = charm.config

        self.peer_app_interface = DataPeerData(
            self.model,
            relation_name=ConnectLiterals.PEER_REL,
            additional_secret_fields=[PeerWorkersContext.ADMIN_PASSWORD],
        )
        self.peer_unit_interface = DataPeerUnitData(
            self.model,
            relation_name=ConnectLiterals.PEER_REL,
            additional_secret_fields=TLSContext.SECRETS,
        )
        self.kafka_client_interface = KafkaRequirerData(
            self.model,
            relation_name=ConnectLiterals.KAFKA_CLIENT_REL,
            topic=ConnectLiterals.TOPICS["offset"],
            extra_user_roles="admin",
        )
        self.connect_provider_interface = KafkaConnectProviderData(
            self.model, relation_name=ConnectLiterals.CLIENT_REL
        )

    @property
    def peer_relation(self) -> Relation | None:
        """The Kafka connect workers peer relation."""
        return self.model.get_relation(ConnectLiterals.PEER_REL)

    @property
    def units(self) -> set[WorkerUnitContext]:
        """Returns a set of peer units' WorkerUnitContext."""
        _set = {self.worker_unit}

        if not self.peer_relation or not self.peer_relation.units:
            return _set

        return _set | {
            WorkerUnitContext(
                relation=self.peer_relation,
                data_interface=DataPeerOtherUnitData(
                    model=self.model, unit=unit, relation_name=ConnectLiterals.PEER_REL
                ),
                component=unit,
            )
            for unit in self.peer_relation.units
        }

    @property
    def kafka_client(self) -> KafkaClientContext:
        """Returns context of the kafka-client relation."""
        return KafkaClientContext(
            self.model.get_relation(ConnectLiterals.KAFKA_CLIENT_REL), self.kafka_client_interface
        )

    @property
    def worker_unit(self) -> WorkerUnitContext:
        """Returns context of the peer unit relation."""
        return WorkerUnitContext(
            self.model.get_relation(ConnectLiterals.PEER_REL),
            self.peer_unit_interface,
            component=self.model.unit,
        )

    @property
    def peer_workers(self) -> PeerWorkersContext:
        """Returns the context of peer app relation."""
        return PeerWorkersContext(
            self.model.get_relation(ConnectLiterals.PEER_REL),
            self.peer_app_interface,
        )

    @property
    def client_relations(self) -> set[Relation]:
        """The relations of all client applications."""
        return set(self.model.relations[ConnectLiterals.CLIENT_REL])

    @property
    def rest_port(self) -> int:
        """Returns the REST API port."""
        return self.config.rest_port

    @property
    def rest_protocol(self) -> str:
        """Returns the REST API protocol, either `http` or `https`."""
        return "http" if not self.peer_workers.tls_enabled else "https"

    @property
    def rest_uri(self) -> str:
        """Returns the REST API base URI of current unit."""
        return self.worker_unit.get_rest_endpoint(protocol=self.rest_protocol, port=self.rest_port)

    @property
    def rest_endpoints(self) -> str:
        """Returns all Kafka Connect REST endpoints available on the cluster."""
        return ",".join(
            [
                unit_context.get_rest_endpoint(protocol=self.rest_protocol, port=self.rest_port)
                for unit_context in self.units
            ]
        )

    @property
    def bind_address(self) -> str:
        """The network binding address from the peer relation."""
        bind_address = ""

        if self.peer_relation:
            if binding := self.model.get_binding(self.peer_relation):
                bind_address = binding.network.bind_address

        return str(bind_address)

    @property
    def clients(self) -> dict[int, ConnectClientContext]:
        """Returns a mapping of integrator relation-id to the related client context."""
        clients = {}
        for relation in self.client_relations:
            if not relation.app:
                continue

            clients[relation.id] = ConnectClientContext(
                relation=relation, data_interface=self.connect_provider_interface
            )

        return clients

    @property
    def credentials(self) -> dict[str, str]:
        """Returns a dict of all active `username: password`s on the Kafka Connect cluster."""
        cache = {}
        if self.peer_workers.admin_password:
            cache[self.peer_workers.ADMIN_USERNAME] = self.peer_workers.admin_password

        for client in self.clients.values():
            cache[client.username] = client.password

        return cache

    @property
    def tls_manager_settings(self) -> TLSManagerSettings:
        """Return TLS manager settings for this unit/app."""
        return TLSManagerSettings(
            app_name=self.worker_unit.unit.app.name,
            unit_name=self.worker_unit.unit.name,
            internal_ca=None,
            internal_ca_key=None,
            keystore_password=self.worker_unit.tls.keystore_password,
            truststore_password=self.worker_unit.tls.truststore_password,
            scopes={
                TLSScope.CONNECT: self.worker_unit.tls,
            },
            peer_cluster_ca=[],
        )

    @property
    @override
    def status(self) -> ConnectStatus:
        if not self.kafka_client.ready:
            return self.kafka_client.status

        return ConnectStatus.ACTIVE


class HealthResponse:
    """Wrapper object for Connect /health response."""

    def __init__(
        self, status_code: int, status: str | None = None, message: str | None = None, **_
    ):
        self.status_code = status_code
        self.status = status
        self.message = message

    def __bool__(self) -> bool:
        """Returns True if 200 status code. Otherwise False."""
        return self.status_code == 200
