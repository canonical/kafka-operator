import logging
import subprocess

from ops.charm import RelationCreatedEvent

logger = logging.getLogger(__name__)

from ops import CharmBase
from ..common.charm import PeerRelationMixin
from literals import PEER
from new.core.models import Status
from new.managers.zookeeper import ZookeeperManager
from ops import RelationChangedEvent, RelationEvent
from ..config import ServerConfig
from new.core.models import CharmState
from new.core.workload import AbstractKafkaService
from new.managers.auth import KafkaAuth


class ZookeeperHandlers(PeerRelationMixin):
    """Implements the provider-side logic for client applications relating to Kafka."""

    PEER = PEER

    def __init__(
            self, charm: CharmBase, state: CharmState, workload: AbstractKafkaService
            # cluster: ClusterRelation, zookeeper: ZookeeperManager,
            # server_config: ServerConfig,
    ) -> None:
        super().__init__(charm, "zookeeper")

        self.state = state
        self.workload = workload
        self.cluster = state.cluster

        self.server_config = ServerConfig(
            self.state.config, self.workload.paths, self.state.cluster, self.state.upgrade,
            self.state.zookeeper, self.state.clients
        )

        auth = KafkaAuth(self.server_config, self.workload)
        self.zookeeper = ZookeeperManager(self.state.zookeeper, auth, self.workload)

    def _on_zookeeper_created(self, event: RelationCreatedEvent) -> None:
        """Handler for `zookeeper_relation_created` events."""
        if self.charm.unit.is_leader():
            event.relation.data[self.charm.app].update({"chroot": "/" + self.charm.app.name})

    def _on_zookeeper_changed(self, event: RelationChangedEvent) -> None:
        """Handler for `zookeeper_relation_created/joined/changed` events, ensuring internal
        users get created."""
        if not self.zookeeper.config.connected:
            logger.debug("No information found from ZooKeeper relation")
            self.charm.app.status = Status.ZK_NO_DATA
            return

        # TLS must be enabled for Kafka and ZK or disabled for both
        if self.cluster.tls.enabled ^ self.zookeeper.config.tls:
            event.defer()
            self.charm.app.status = Status.ZK_TLS_MISMATCH
            return

        # do not create users until certificate + keystores created
        # otherwise unable to authenticate to ZK
        if self.cluster.tls.enabled and not self.cluster.tls.certificate:
            event.defer()
            self.charm.app.status = Status.NO_CERT
            return

        if not self.cluster.internal_user_credentials and self.charm.unit.is_leader():
            # loading the minimum config needed to authenticate to zookeeper
            self.zookeeper.set_zk_jaas_config()
            self.zookeeper.set_server_properties(self.server_config)

            try:
                internal_user_credentials = self.zookeeper.create_internal_credentials()
            except (KeyError, RuntimeError, subprocess.CalledProcessError) as e:
                logger.warning(str(e))
                event.defer()
                return

            # only set to relation data when all set
            for username, password in internal_user_credentials:
                self.set_secret(scope="app", key=f"{username}-password", value=password)

        self._on_config_changed(event)

    def _on_zookeeper_broken(self, _: RelationEvent) -> None:
        """Handler for `zookeeper_relation_broken` event, ensuring charm blocks."""
        self.zookeeper.workload.stop()

        logger.info(f'Broker {self.cluster.unit.unit} disconnected')
        self.charm.app.status = Status.ZK_NOT_RELATED
