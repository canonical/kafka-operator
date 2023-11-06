from typing import Optional, MutableMapping, Mapping

from ops import CharmBase, Relation, Object


class PeerRelationMixin(Object):
    PEER: str
    charm: CharmBase

    @property
    def peer_relation(self) -> Optional[Relation]:
        """The cluster peer relation."""
        return self.model.get_relation(self.PEER)

    @property
    def app_peer_data(self) -> MutableMapping[str, str]:
        """Application peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.charm.app]

    @property
    def unit_peer_data(self) -> MutableMapping[str, str]:
        """Unit peer relation data object."""
        if not self.peer_relation:
            return {}

        return self.peer_relation.data[self.charm.unit]

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
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


def get_secret(data: Mapping[str, str], key: str) -> Optional[str]:
    """Get TLS secret from the secret storage.

    Args:
        scope: whether this secret is for a `unit` or `app`
        key: the secret key name

    Returns:
        String of key value.
        None if non-existent key
    """
    return data.get(key)
