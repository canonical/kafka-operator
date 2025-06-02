#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import logging
import os
import shutil
import subprocess
from socket import getfqdn

from charms.data_platform_libs.v0.data_interfaces import KafkaRequires, TopicCreatedEvent
from charms.operator_libs_linux.v1 import snap
from ops.charm import ActionEvent, CharmBase, RelationEvent
from ops.main import main
from ops.model import ActiveStatus
from utils import safe_write_to_file

logger = logging.getLogger(__name__)

CHARM_KEY = "app"
PEER = "cluster"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
ZK = "zookeeper"
CONSUMER_GROUP_PREFIX = "test-prefix"
SNAP_PATH = "/var/snap/charmed-kafka/current/etc/kafka"
DEFAULT_TOPIC_NAME = "test-topic"


class ApplicationCharm(CharmBase):
    """Application charm that connects to database charms."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = CHARM_KEY

        if self.config["topic-name"] != DEFAULT_TOPIC_NAME:
            self.topic_name = self.config["topic-name"]
        else:
            self.topic_name = DEFAULT_TOPIC_NAME

        self.framework.observe(getattr(self.on, "start"), self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.kafka_requirer_consumer = KafkaRequires(
            self,
            relation_name=REL_NAME_CONSUMER,
            topic=self.topic_name,
            extra_user_roles="consumer",
            consumer_group_prefix=CONSUMER_GROUP_PREFIX,
        )
        self.kafka_requirer_producer = KafkaRequires(
            self,
            relation_name=REL_NAME_PRODUCER,
            topic=self.topic_name,
            extra_user_roles="producer",
        )
        self.kafka_requirer_admin = KafkaRequires(
            self, relation_name=REL_NAME_ADMIN, topic=self.topic_name, extra_user_roles="admin"
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

        self.framework.observe(
            getattr(self.on, "create_certificate_action"), self.create_certificate
        )
        self.framework.observe(
            getattr(self.on, "run_mtls_producer_action"), self.run_mtls_producer
        )
        self.framework.observe(getattr(self.on, "get_offsets_action"), self.get_offsets)
        self.framework.observe(getattr(self.on, "create_topic_action"), self.create_topic)

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def _on_update_status(self, _) -> None:
        logger.info("Update Status")

    def _log(self, _: RelationEvent):
        return

    def on_topic_created_consumer(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        if not (peer_relation := self.model.get_relation("cluster")):
            event.defer()
            return

        peer_relation.data[self.app]["username"] = event.username or ""
        peer_relation.data[self.app]["password"] = event.password or ""
        peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        peer_relation.data[self.app]["tls"] = event.tls or ""

        return

    def on_topic_created_producer(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        if not (peer_relation := self.model.get_relation("cluster")):
            event.defer()
            return

        peer_relation.data[self.app]["username"] = event.username or ""
        peer_relation.data[self.app]["password"] = event.password or ""
        peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        peer_relation.data[self.app]["tls"] = event.tls or ""

        return

    def on_topic_created_admin(self, event: TopicCreatedEvent):
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        if not (peer_relation := self.model.get_relation("cluster")):
            event.defer()
            return

        peer_relation.data[self.app]["username"] = event.username or ""
        peer_relation.data[self.app]["password"] = event.password or ""
        peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        peer_relation.data[self.app]["tls"] = event.tls or ""

        return

    def _install_packages(self):
        logger.info("INSTALLING PACKAGES")
        cache = snap.SnapCache()
        kafka = cache["charmed-kafka"]

        kafka.ensure(snap.SnapState.Latest, channel="3/edge", revision=19)

    @staticmethod
    def set_snap_ownership(path: str) -> None:
        """Sets a filepath `snap_daemon` ownership."""
        shutil.chown(path, user="snap_daemon", group="root")

        for root, dirs, files in os.walk(path):
            for fp in dirs + files:
                shutil.chown(os.path.join(root, fp), user="snap_daemon", group="root")

    @staticmethod
    def set_snap_mode_bits(path: str) -> None:
        """Sets filepath mode bits."""
        os.chmod(path, 0o774)

        for root, dirs, files in os.walk(path):
            for fp in dirs + files:
                os.chmod(os.path.join(root, fp), 0o774)

    def _create_keystore(self, unit_name: str, unit_host: str):
        try:
            logger.info("creating the keystore")
            subprocess.check_output(
                f'charmed-kafka.keytool -keystore client.keystore.jks -alias client-key -validity 90 -genkey -keyalg RSA -noprompt -storepass password -dname "CN=client" -ext SAN=DNS:{unit_name},IP:{unit_host}',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            self.set_snap_ownership(path=f"{SNAP_PATH}/client.keystore.jks")
            self.set_snap_mode_bits(path=f"{SNAP_PATH}/client.keystore.jks")

            logger.info("creating a ca")
            subprocess.check_output(
                'openssl req -new -x509 -keyout ca.key -out ca.cert -days 90 -passout pass:password -subj "/CN=client-ca"',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            self.set_snap_ownership(path=f"{SNAP_PATH}/ca.key")
            self.set_snap_ownership(path=f"{SNAP_PATH}/ca.cert")

            logger.info("signing certificate")
            subprocess.check_output(
                "charmed-kafka.keytool -keystore client.keystore.jks -alias client-key -certreq -file client.csr -storepass password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            self.set_snap_ownership(path=f"{SNAP_PATH}/client.csr")

            subprocess.check_output(
                "openssl x509 -req -CA ca.cert -CAkey ca.key -in client.csr -out client.cert -days 90 -CAcreateserial -passin pass:password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            self.set_snap_ownership(path=f"{SNAP_PATH}/client.cert")

            logger.info("importing certificate to keystore")
            subprocess.check_output(
                "charmed-kafka.keytool -keystore client.keystore.jks -alias client-cert -importcert -file client.cert -storepass password -noprompt",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            self.set_snap_ownership(path=f"{SNAP_PATH}/client.keystore.jks")
            self.set_snap_mode_bits(path=f"{SNAP_PATH}/client.keystore.jks")

            logger.info("grabbing cert content")
            certificate = subprocess.check_output(
                "cat client.cert",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            ca = subprocess.check_output(
                "cat ca.cert",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )

        except subprocess.CalledProcessError as e:
            logger.exception(e)
            raise e

        return {"certificate": certificate, "ca": ca}

    def _create_truststore(self, broker_ca: str):
        logger.info("writing broker cert to unit")
        safe_write_to_file(content=broker_ca, path=f"{SNAP_PATH}/broker.cert")

        # creating truststore and importing cert files
        for file in ["broker.cert", "ca.cert", "client.cert"]:
            try:
                logger.info(f"adding {file} to truststore")
                subprocess.check_output(
                    f"charmed-kafka.keytool -keystore client.truststore.jks -alias {file.replace('.', '-')} -importcert -file {file} -storepass password -noprompt",
                    stderr=subprocess.STDOUT,
                    shell=True,
                    universal_newlines=True,
                    cwd=SNAP_PATH,
                )
                self.set_snap_ownership(path=f"{SNAP_PATH}/client.truststore.jks")
                self.set_snap_mode_bits(path=f"{SNAP_PATH}/client.truststore.jks")
            except subprocess.CalledProcessError as e:
                # in case this reruns and fails
                if "already exists" in e.output:
                    logger.exception(e)
                    continue
                raise e

        logger.info("creating client.properties file")
        properties = [
            "security.protocol=SSL",
            f"ssl.truststore.location={SNAP_PATH}/client.truststore.jks",
            f"ssl.keystore.location={SNAP_PATH}/client.keystore.jks",
            "ssl.truststore.password=password",
            "ssl.keystore.password=password",
            "ssl.key.password=password",
        ]
        safe_write_to_file(
            content="\n".join(properties),
            path=f"{SNAP_PATH}/client.properties",
        )

    def _attempt_mtls_connection(self, bootstrap_servers: str, num_messages: int):
        logger.info("creating data to feed to producer")
        content = "\n".join(f"message: {ith}" for ith in range(num_messages))

        safe_write_to_file(content=content, path=f"{SNAP_PATH}/data")

        logger.info("Creating topic")
        try:
            subprocess.check_output(
                f"charmed-kafka.topics --bootstrap-server {bootstrap_servers} --topic={self.topic_name} --create --command-config client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            raise e

        logger.info("running producer application")
        try:
            subprocess.check_output(
                f"cat data | charmed-kafka.console-producer --bootstrap-server {bootstrap_servers} --topic={self.topic_name} --producer.config client.properties -",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            raise e

    def create_certificate(self, event: ActionEvent):
        peer_relation = self.model.get_relation("cluster")
        if not peer_relation:
            logger.error("peer relation not ready")
            raise Exception("peer relation not ready")

        self._install_packages()

        unit_host = peer_relation.data[self.unit].get("private-address" "") or ""
        unit_name = getfqdn()

        response = self._create_keystore(unit_host=unit_host, unit_name=unit_name)

        event.set_results(
            {"client-certificate": response["certificate"], "client-ca": response["ca"]}
        )

        # Activate MTLS by setting the mtls-cert field on relation
        producer_relation = self.model.get_relation(REL_NAME_PRODUCER)
        self.kafka_requirer_producer.set_mtls_cert(producer_relation.id, response["certificate"])

    def run_mtls_producer(self, event: ActionEvent):
        producer_relation = self.model.get_relation(REL_NAME_PRODUCER)
        broker_data = (
            self.kafka_requirer_producer.as_dict(producer_relation.id) if producer_relation else {}
        )
        broker_ca = broker_data.get("tls-ca")
        bootstrap_server = broker_data.get("endpoints")

        if not broker_ca or not bootstrap_server:
            event.fail("Can't fetch Broker data from the relation.")
            return

        num_messages = int(event.params["num-messages"])
        try:
            self._create_truststore(broker_ca=broker_ca)
            self._attempt_mtls_connection(
                bootstrap_servers=bootstrap_server, num_messages=num_messages
            )
        except Exception as e:
            logger.exception(e)
            event.fail()
            return

        event.set_results({"success": "TRUE"})

    def get_offsets(self, event: ActionEvent):
        bootstrap_server = event.params["bootstrap-server"]

        logger.info("fetching offsets")
        try:
            output = subprocess.check_output(
                f"charmed-kafka.get-offsets --bootstrap-server {bootstrap_server} --topic={self.topic_name} --command-config client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            event.set_results({"output": output})
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            event.fail()

        return

    def create_topic(self, event: ActionEvent) -> None:
        logger.info("creating client.properties file")
        if not (peer_relation := self.model.get_relation("cluster")):
            event.fail("No peer relation")
            return

        self._install_packages()

        username = peer_relation.data[self.app]["username"]
        password = peer_relation.data[self.app]["password"]
        bootstrap_server = peer_relation.data[self.app]["bootstrap-server"]

        properties = [
            f'sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="{username}" password="{password}";',
            "sasl.mechanism=SCRAM-SHA-512",
            "security.protocol=SASL_PLAINTEXT",
            f"bootstrap.servers={bootstrap_server}",
        ]

        safe_write_to_file(
            content="\n".join(properties),
            path=f"{SNAP_PATH}/client.properties",
        )

        logger.info("creating topic")
        try:
            subprocess.check_output(
                # if requested acls for prefixed `test-*`, should be able to create `test-topic`
                f"charmed-kafka.topics --bootstrap-server {bootstrap_server} --topic={DEFAULT_TOPIC_NAME} --create --command-config client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                cwd=SNAP_PATH,
            )
            event.set_results({"success": "TRUE"})

        except subprocess.CalledProcessError as e:
            logger.exception(vars(e))
            event.set_results({"success": "FALSE"})
            event.fail()

        return


if __name__ == "__main__":
    main(ApplicationCharm)
