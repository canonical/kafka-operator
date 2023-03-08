#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import logging
import subprocess

from charms.data_platform_libs.v0.data_interfaces import KafkaRequires, TopicCreatedEvent
from ops.charm import ActionEvent, CharmBase, RelationEvent
from ops.main import main
from ops.model import ActiveStatus
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap
from utils import safe_write_to_file

logger = logging.getLogger(__name__)


CHARM_KEY = "app"
PEER = "cluster"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
ZK = "zookeeper"
CONSUMER_GROUP_PREFIX = "test-prefix"


class ApplicationCharm(CharmBase):
    """Application charm that connects to database charms."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.kafka_requirer_consumer = KafkaRequires(
            self,
            relation_name=REL_NAME_CONSUMER,
            topic="test-topic",
            extra_user_roles="consumer",
            consumer_group_prefix=CONSUMER_GROUP_PREFIX,
        )
        self.kafka_requirer_producer = KafkaRequires(
            self, relation_name=REL_NAME_PRODUCER, topic="test-topic", extra_user_roles="producer"
        )
        self.kafka_requirer_admin = KafkaRequires(
            self, relation_name=REL_NAME_ADMIN, topic="test-topic", extra_user_roles="admin"
        )
        self.framework.observe(
            self.kafka_requirer_consumer.on.topic_created, self.on_topic_created_consumer
        )
        self.framework.observe(
            self.kafka_requirer_producer.on.topic_created, self.on_topic_created_producer
        )
        self.framework.observe(
            self.kafka_requirer_admin.on.topic_created, self.on_topic_created_admin
        )

        self.framework.observe(getattr(self.on, "create_keystores_action"), self._action)

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def _log(self, event: RelationEvent):
        return

    def on_topic_created_consumer(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def on_topic_created_producer(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def on_topic_created_admin(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        return

    def _install_packages(self):
        apt.update()
        apt.add_package(["snapd", "openjdk-17-jre-headless"])
        cache = snap.SnapCache()
        kafka = cache["charmed-kafka"]

        if not kafka.present:
            kafka.ensure(snap.SnapState.Latest, channel="latest/edge")

    def _create_keystore(self, event: ActionEvent):
        peer_relation = self.model.get_relation("cluster")
        if not peer_relation:
            event.fail("no peer relation")
            return

        unit_host = peer_relation.data[self.unit].get("private-address" "")
        unit_name = self.unit.name

        try:
            # creating the keystore
            subprocess.check_output(
                f'keytool -keystore client.keystore.jks -alias client-key -validity 90 -genkey -keyalg RSA -noprompt -storepass password -dname "CN=client" -ext SAN=DNS:{unit_name},IP:{unit_host}',
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
            )

            # creating a CA
            subprocess.check_output(
                f'openssl req -new -x509 -keyout ca.key -out ca.cert -days 90 -passout pass:password -subj "/CN=client-ca"',
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
            )

            # signing certificate
            subprocess.check_output(
                f"keytool -keystore client.keystore.jks -alias client-key -certreq -file client.csr -storepass password",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
            )
            subprocess.check_output(
                f"openssl x509 -req -CA ca.cert -CAkey ca.key -in client.csr -out client.cert -days 90 -CAcreateserial -passin pass:password",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
            )

            # importing certificate to keystore
            subprocess.check_output(
                f"keytool -keystore client.keystore.jks -alias client-cert -importcert -file client.cert -storepass password",
                stderr=subprocess.PIPE,
                shell=True,
                universal_newlines=True,
            )

            # grabbing cert content
            certificate = subprocess.check_output(
                "cat client.cert", stderr=subprocess.PIPE, shell=True, universal_newlines=True
            )

        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

        event.set_results({"client-certificate": certificate})

    def _create_truststore(self, event: ActionEvent):
        broker_ca = event.params["broker-ca"]

        safe_write_to_file(content=broker_ca, path="broker.cert") 

        try:
            # creating truststore and importing cert files
            for file in ["broker.cert", "ca.cert", "client.cert"]:
                subprocess.check_output(
                    f"keytool -keystore client.truststore.jks -alias broker-ca -importcert -file {file} -storepass password",
                    stderr=subprocess.PIPE,
                    shell=True,
                    universal_newlines=True,
                )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            raise e

        return

    def _create_data(self, _):
        

    def _attempt_mtls_connection(self, _):
        subprocess.check_output(
            "/"

        )


if __name__ == "__main__":
    main(ApplicationCharm)
