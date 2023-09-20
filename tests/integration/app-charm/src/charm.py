#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import base64
import logging
import shutil
import subprocess
from socket import getfqdn

from charms.data_platform_libs.v0.data_interfaces import KafkaRequires, TopicCreatedEvent
from charms.operator_libs_linux.v0 import apt
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
CHARMED_KAFKA_SNAP_REVISION = 19


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

        self.framework.observe(
            getattr(self.on, "create_certificate_action"), self.create_certificate
        )
        self.framework.observe(
            getattr(self.on, "run_mtls_producer_action"), self.run_mtls_producer
        )
        self.framework.observe(getattr(self.on, "get_offsets_action"), self.get_offsets)

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def _log(self, _: RelationEvent):
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
        logger.info("INSTALLING PACKAGES")
        apt.update()
        apt.add_package(["snapd"])
        cache = snap.SnapCache()
        kafka = cache["charmed-kafka"]

        kafka.ensure(snap.SnapState.Latest, channel="3/edge", revision=19)

    def _create_keystore(self, unit_name: str, unit_host: str):
        try:
            logger.info("creating the keystore")
            subprocess.check_output(
                f'charmed-kafka.keytool -keystore {SNAP_PATH}/client.keystore.jks -alias client-key -validity 90 -genkey -keyalg RSA -noprompt -storepass password -dname "CN=client" -ext SAN=DNS:{unit_name},IP:{unit_host}',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            shutil.chown(f"{SNAP_PATH}/client.keystore.jks", user="snap_daemon", group="root")

            logger.info("creating a ca")
            subprocess.check_output(
                f'openssl req -new -x509 -keyout {SNAP_PATH}/ca.key -out {SNAP_PATH}/ca.cert -days 90 -passout pass:password -subj "/CN=client-ca"',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            shutil.chown(f"{SNAP_PATH}/ca.key", user="snap_daemon", group="root")
            shutil.chown(f"{SNAP_PATH}/ca.cert", user="snap_daemon", group="root")

            logger.info("signing certificate")
            subprocess.check_output(
                f"charmed-kafka.keytool -keystore {SNAP_PATH}/client.keystore.jks -alias client-key -certreq -file {SNAP_PATH}/client.csr -storepass password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            shutil.chown(f"{SNAP_PATH}/client.csr", user="snap_daemon", group="root")

            subprocess.check_output(
                f"openssl x509 -req -CA {SNAP_PATH}/ca.cert -CAkey {SNAP_PATH}/ca.key -in {SNAP_PATH}/client.csr -out {SNAP_PATH}/client.cert -days 90 -CAcreateserial -passin pass:password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            shutil.chown(f"{SNAP_PATH}/client.cert", user="snap_daemon", group="root")

            logger.info("importing certificate to keystore")
            subprocess.check_output(
                f"sudo charmed-kafka.keytool -keystore {SNAP_PATH}/client.keystore.jks -alias client-cert -importcert -file {SNAP_PATH}/client.cert -storepass password -noprompt",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            shutil.chown(f"{SNAP_PATH}/client.keystore.jks", user="snap_daemon", group="root")

            logger.info("grabbing cert content")
            certificate = subprocess.check_output(
                f"cat {SNAP_PATH}/client.cert",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            ca = subprocess.check_output(
                f"cat {SNAP_PATH}/ca.cert",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
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
                    f"charmed-kafka.keytool -keystore {SNAP_PATH}/client.truststore.jks -alias {file.replace('.', '-')} -importcert -file {SNAP_PATH}/{file} -storepass password -noprompt",
                    stderr=subprocess.STDOUT,
                    shell=True,
                    universal_newlines=True,
                )
                shutil.chown(
                    f"{SNAP_PATH}/client.truststore.jks", user="snap_daemon", group="root"
                )
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
                f"charmed-kafka.topics --bootstrap-server {bootstrap_servers} --topic=TEST-TOPIC --create --command-config {SNAP_PATH}/client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            raise e

        logger.info("running producer application")
        try:
            subprocess.check_output(
                f"charmed-kafka.console-producer --bootstrap-server {bootstrap_servers} --topic=TEST-TOPIC --producer.config {SNAP_PATH}/client.properties < {SNAP_PATH}/data",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
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

        logger.info(f"{unit_host=}")
        logger.info(f"{unit_name=}")

        response = self._create_keystore(unit_host=unit_host, unit_name=unit_name)

        logger.info(f"{response=}")

        event.set_results(
            {"client-certificate": response["certificate"], "client-ca": response["ca"]}
        )

    def run_mtls_producer(self, event: ActionEvent):
        broker_ca = event.params["broker-ca"]
        bootstrap_server = event.params["bootstrap-server"]
        num_messages = int(event.params["num-messages"])

        decode_cert = base64.b64decode(broker_ca).decode("utf-8").strip()

        try:
            self._create_truststore(broker_ca=decode_cert)
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
                f"charmed-kafka.get-offsets --bootstrap-server {bootstrap_server} --topic=TEST-TOPIC --command-config {SNAP_PATH}/client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            event.set_results({"output": output})
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            event.fail()

        return


if __name__ == "__main__":
    main(ApplicationCharm)
