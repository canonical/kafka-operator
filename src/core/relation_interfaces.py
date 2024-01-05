#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Supporting objects for Kafka charm relation interfaces."""

from typing import MutableMapping, Optional, Set
from ops import Unit

from ops.framework import Framework, Object
from ops.model import Relation, Application

from core.literals import PEER, ZK, TLS_RELATION, DatabagScope


class ClusterRelation(Object):
    """Kafka cluster peer relation interface."""

    def __init__(self, charm):
        super().__init__(charm, "cluster_interface")

    # CLUSTER PEER RELATION DATABAG

    @property
    def peer_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(PEER)

    @property
    def units(self) -> Set[Unit]:
        """Units of the relation."""
        if not self.peer_relation:
            return set()
        return self.peer_relation.units

    @property
    def app_peer_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.model.app]

    def unit_peer_data(self, unit: Unit | None = None) -> MutableMapping[str, str]:
        """Unit peer relation data object."""
        if not self.peer_relation:
            return {}

        unit = unit or self.model.unit
        return self.peer_relation.data[unit]

    def update(self, values: dict, scope: DatabagScope = "app") -> None:
        """Update databag.

        Args:
            scope: whether the values are for a `unit` or `app`
            values: dict with the values to update
        """
        if scope == "unit":
            self.unit_peer_data.update(values)
        elif scope == "app":
            self.app_peer_data.update(values)
        else:
            raise RuntimeError("Unknown secret scope.")

    def get_secret(self, scope: DatabagScope, key: str) -> Optional[str]:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name

        Returns:
            String of key value.
            None if non-existent key
        """
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: DatabagScope, key: str, value: Optional[str]) -> None:
        """Get TLS secret from the secret storage.

        Args:
            scope: whether this secret is for a `unit` or `app`
            key: the secret key name
            value: the value for the secret key
        """
        if scope == "unit":
            if not value:
                self.unit_peer_data.update({key: ""})
                return
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                self.app_peer_data.update({key: ""})
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")


class ZooKeeperRelation(Object):
    """ZooKeeper relation interface."""

    def __init__(self, charm: Framework | Object):
        super().__init__(charm, "zookeeper_interface")

    @property
    def zookeeper_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(ZK)

    # REMOTE ENTITIES DATA

    @property
    def remote_zookeeper_app(self) -> Application | None:
        """Remote ZooKeeper application."""
        if not self.zookeeper_relation:
            return None

        return self.zookeeper_relation.app

    @property
    def remote_zookeeper_app_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.remote_zookeeper_app or not self.zookeeper_relation:
            return {}

        return self.zookeeper_relation.data[self.remote_zookeeper_app]


class CertificatesRelation(Object):
    """Certificates relation interface."""

    def __init__(self, charm: Framework | Object):
        super().__init__(charm, "certificates_interface")

    @property
    def certificates_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(TLS_RELATION)

    # REMOTE ENTITIES DATA

    @property
    def remote_certificates_app(self) -> Application | None:
        """Remote certificates application."""
        if not self.certificates_relation:
            return None

        return self.certificates_relation.app

    @property
    def remote_zookeeper_app_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.remote_certificates_app or not self.certificates_relation:
            return {}

        return self.certificates_relation.data[self.remote_certificates_app]
