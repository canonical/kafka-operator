import os
from typing import Mapping, List

from ops import StorageMapping

from charms.data_platform_libs.v0.data_models import TypedCharmBase
from literals import PEER, ZK, REL_NAME

from new.common.charm import get_secret
from new.core.models import CharmState, KafkaConfig
from new.core.models import Storage
from new.core.models import ZookeeperConfig, ClusterRelation, KafkaClient
from structured_config import CharmConfig

_ZK_KEYS = ["username", "password", "endpoints", "chroot", "uris", "tls"]

_INTERNAL_USERS = ["sync", "admin"]

def zookeeper_config(relation_data: Mapping[str, str]) -> ZookeeperConfig:
    """The config from current ZooKeeper relations for data necessary for broker connection.

    Returns:
        Dict of ZooKeeeper:
        `username`, `password`, `endpoints`, `chroot`, `connect`, `uris` and `tls`
    """
    # loop through all relations to ZK, attempt to find all needed config

    missing_config = any(relation_data.get(key, None) is None for key in _ZK_KEYS)

    # skip if config is missing
    if missing_config:
        raise ValueError(f"Relation data missing information for Zookeeper")

    zookeeper_config = {}

    sorted_uris = sorted(
        zookeeper_config["uris"].replace(zookeeper_config["chroot"], "").split(",")
    )
    sorted_uris[-1] = sorted_uris[-1] + zookeeper_config["chroot"]
    zookeeper_config["connect"] = ",".join(sorted_uris)

    return ZookeeperConfig(**zookeeper_config)


from ops import Unit, Relation
from new.core.models import Broker


def cluster_relation(unit: Unit, peer_relation: Relation) -> ClusterRelation:
    app_data = peer_relation.data[peer_relation.app]
    unit_data = peer_relation.data[unit]

    parsed = dict()

    parsed["unit"] = Broker(
        address=unit_data.get("private-address", ""),
        host=unit.name,
        unit=int(unit.name.split("/")[1])
    )

    credentials = {
        user: password
        for user in _INTERNAL_USERS
        if (password := get_secret(app_data, key=f"{user}-password"))
    }

    parsed["internal_user_credentials"] = \
        credentials if len(credentials) == len(_INTERNAL_USERS) else {}

    units: List[Unit] = list(set([unit] + list(peer_relation.units)))
    parsed["hosts"] = [Broker(
        host=unit.name,
        unit=int(unit.name.split("/")[1]),
        address=peer_relation.data[unit].get("private-address")
    ) for unit in units]

    # TLS
    tls = {}
    if app_data.get("tls", "disabled") == "enabled":
        tls["enabled"] = app_data["tls"] == "enabled"
        tls["mtls_enabled"] = app_data["mtls_enabled"] == "enabled"
        tls["private_key"] = get_secret(unit_data, "private-key")
        tls["csr"] = get_secret(unit_data, "csr")
        tls["certificate"] = get_secret(unit_data, "certificate")
        tls["ca"] = get_secret(unit_data, "ca")
        tls["keystore_password"] = get_secret(unit_data, "keystore-password")
        tls["truststore_password"] = get_secret(unit_data, "truststore-password")

    parsed["tls"] = tls

    return ClusterRelation(**parsed)


def kafka_client(
        relation_id: int, relation_data: Mapping[str, str], peer_data: Mapping[str, str]
) -> KafkaClient:
    username = f"relation-{relation_id}"
    return KafkaClient(
        username=username,
        password=peer_data.get(username),
        extra_user_roles=set(relation_data["extra-user-roles"].split(","))
    )


def kafka_clients(
        relations: List[Relation], peer_data: Mapping[str, str]
) -> dict[int, KafkaClient]:
    return {
        relation.id: kafka_client(relation.id, relation.data[relation.app], peer_data)
        for relation in relations
    }


def storages(charm_storages: StorageMapping):
    return {
        key: [Storage(location=os.fspath(storage.location)) for storage in storage_group]
        for key, storage_group in charm_storages.items()
    }


def charm_state(charm: TypedCharmBase[CharmConfig]):
    kafka_config = KafkaConfig(
        planned_units=charm.app.planned_units(),
        storages=storages(charm.model.storages),
        **charm.config.dict()
    )
    cluster = cluster_relation(charm.unit, relation) \
        if (relation := charm.model.get_relation(PEER)) else None

    # upgrade: UpgradeRelation | None = None
    zookeeper = zookeeper_config(relation.data[relation.app]) if (
        relation := charm.model.get_relation(ZK)) \
        else None

    clients: dict[int, KafkaClient] = kafka_clients(
        charm.model.relations[REL_NAME], charm.model.get_relation(PEER).data[charm.app]
    )

    return CharmState(
        config=kafka_config,
        cluster=cluster,
        upgrade=None,
        zookeeper=zookeeper,
        clients=clients
    )
