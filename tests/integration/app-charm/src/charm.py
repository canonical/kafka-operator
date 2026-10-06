#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Application charm that connects to database charms.

This charm is meant to be used only for testing
of the libraries in this repository.
"""

import base64
import logging
import subprocess
from socket import getfqdn

from charms.data_platform_libs.v0.data_interfaces import KafkaRequires, TopicCreatedEvent
from client import KafkaClient
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import ActiveStatus, Relation
from utils import safe_write_to_file

logger = logging.getLogger(__name__)


CHARM_KEY = "app"
PEER = "cluster"
REL_NAME_CONSUMER = "kafka-client-consumer"
REL_NAME_PRODUCER = "kafka-client-producer"
REL_NAME_ADMIN = "kafka-client-admin"
ZK = "zookeeper"
CONSUMER_GROUP_PREFIX = "test-prefix"
KAFKA_VERSION = "3.7.1"
KAFKA_DIR = "kafka_2.13-3.7.1"


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

        # this action is needed because hostnames cannot be resolved outside K8s
        self.framework.observe(getattr(self.on, "produce_action"), self._produce)

        # this action is needed to validate a consumer, which will raise if it can't read at least 3 messages
        self.framework.observe(getattr(self.on, "consume_action"), self._consume)

        self.framework.observe(
            getattr(self.on, "create_certificate_action"), self.create_certificate
        )
        self.framework.observe(
            getattr(self.on, "run_mtls_producer_action"), self.run_mtls_producer
        )
        self.framework.observe(getattr(self.on, "get_offsets_action"), self.get_offsets)

    @property
    def peer_relation(self) -> Relation | None:
        return self.model.get_relation("cluster")

    def _on_start(self, _) -> None:
        self.unit.status = ActiveStatus()

    def on_topic_created_consumer(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        self.peer_relation.data[self.app]["username"] = event.username or ""
        self.peer_relation.data[self.app]["password"] = event.password or ""
        self.peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        return

    def on_topic_created_producer(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        self.peer_relation.data[self.app]["username"] = event.username or ""
        self.peer_relation.data[self.app]["password"] = event.password or ""
        self.peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        return

    def on_topic_created_admin(self, event: TopicCreatedEvent) -> None:
        logger.info(f"{event.username} {event.password} {event.bootstrap_server} {event.tls}")
        self.peer_relation.data[self.app]["username"] = event.username or ""
        self.peer_relation.data[self.app]["password"] = event.password or ""
        self.peer_relation.data[self.app]["bootstrap-server"] = event.bootstrap_server or ""
        return

    def _install_packages(self):
        subprocess.check_output(
            "apt update && DEBIAN_FRONTEND=noninteractive apt install openjdk-21-jre-headless -y -qq",
            stderr=subprocess.STDOUT,
            shell=True,
            universal_newlines=True,
        )
        subprocess.check_output(
            "apt install wget",
            stderr=subprocess.STDOUT,
            shell=True,
            universal_newlines=True,
        )
        subprocess.check_output(
            f"wget https://archive.apache.org/dist/kafka/{KAFKA_VERSION}/{KAFKA_DIR}.tgz && tar -xvzf {KAFKA_DIR}.tgz",
            stderr=subprocess.STDOUT,
            shell=True,
            universal_newlines=True,
        )

    def _create_keystore(self) -> dict[str, str]:
        if not (peer_relation := self.model.get_relation("cluster")):
            logger.error("no peer relation")
            return {}
        if not (binding := self.model.get_binding(peer_relation)):
            logger.error("no binding")
            return {}

        unit_id = self.unit.name.split("/")[1]
        bind_address = binding.network.bind_address
        internal_address = f"{self.app.name}-{unit_id}.{self.app.name}-endpoints"
        fqdn = getfqdn()
        pod_name = f"{self.app.name}-{unit_id}"

        try:
            logger.info("creating the keystore")
            subprocess.check_output(
                f'keytool -keystore client.keystore.jks -alias client-key -validity 90 -genkey -keyalg RSA -noprompt -storepass password -dname "CN=client" -ext SAN=DNS:{pod_name},DNS:{internal_address},DNS:{fqdn},IP:{bind_address}',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )

            logger.info("creating a ca")
            subprocess.check_output(
                'openssl req -new -x509 -keyout ca.key -out ca.cert -days 90 -passout pass:password -subj "/CN=client-ca"',
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )

            logger.info("signing certificate")
            subprocess.check_output(
                "keytool -keystore client.keystore.jks -alias client-key -certreq -file client.csr -storepass password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )

            subprocess.check_output(
                "openssl x509 -req -CA ca.cert -CAkey ca.key -in client.csr -out client.cert -days 90 -CAcreateserial -passin pass:password",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )

            logger.info("importing certificate to keystore")
            subprocess.check_output(
                "keytool -keystore client.keystore.jks -alias client-cert -importcert -file client.cert -storepass password -noprompt",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )

            logger.info("grabbing cert content")
            certificate = subprocess.check_output(
                "cat client.cert",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
            )
            ca = subprocess.check_output(
                "cat ca.cert",
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
        safe_write_to_file(content=broker_ca, path="broker.cert")

        # creating truststore and importing cert files
        for file in ["broker.cert", "ca.cert", "client.cert"]:
            try:
                logger.info(f"adding {file} to truststore")
                subprocess.check_output(
                    f"keytool -keystore client.truststore.jks -alias {file.replace('.', '-')} -importcert -file {file} -storepass password -noprompt",
                    stderr=subprocess.STDOUT,
                    shell=True,
                    universal_newlines=True,
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
            "ssl.truststore.location=client.truststore.jks",
            "ssl.keystore.location=client.keystore.jks",
            "ssl.truststore.password=password",
            "ssl.keystore.password=password",
            "ssl.key.password=password",
        ]
        safe_write_to_file(
            content="\n".join(properties),
            path="client.properties",
        )

    def _attempt_mtls_connection(self, bootstrap_servers: str, num_messages: int):
        logger.info("creating data to feed to producer")
        content = "\n".join(f"message: {ith}" for ith in range(num_messages))

        safe_write_to_file(content=content, path="data")

        logger.info("Creating topic")
        try:
            subprocess.check_output(
                f"{KAFKA_DIR}/bin/kafka-topics.sh --bootstrap-server {bootstrap_servers} --topic=TEST-TOPIC --create --command-config client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                env={"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64"},
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e.stdout)
            logger.exception(e.stderr)
            raise e

        logger.info("running producer application")
        try:
            subprocess.check_output(
                f"cat data | {KAFKA_DIR}/bin/kafka-console-producer.sh --bootstrap-server {bootstrap_servers} --topic=TEST-TOPIC --producer.config client.properties -",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                env={"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64"},
            )
        except subprocess.CalledProcessError as e:
            logger.exception(e.stdout)
            logger.exception(e.stderr)
            raise e

    def create_certificate(self, event: ActionEvent):
        peer_relation = self.model.get_relation("cluster")
        if not peer_relation:
            logger.error("peer relation not ready")
            raise Exception("peer relation not ready")

        self._install_packages()

        response = self._create_keystore()

        event.set_results(
            {"client-certificate": response["certificate"], "client-ca": response["ca"]}
        )

    def run_mtls_producer(self, event: ActionEvent):
        broker_ca = event.params["broker-ca"]
        mtls_nodeport = event.params["mtls-nodeport"]
        endpoints = self.peer_relation.data[self.app]["bootstrap-server"].split(":")[0]
        bootstrap_server = f"{endpoints}:{mtls_nodeport}"
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
        mtls_nodeport = event.params["mtls-nodeport"]
        endpoints = self.peer_relation.data[self.app]["bootstrap-server"].split(":")[0]
        bootstrap_server = f"{endpoints}:{mtls_nodeport}"

        try:
            output = subprocess.check_output(
                f"{KAFKA_DIR}/bin/kafka-get-offsets.sh --bootstrap-server {bootstrap_server} --topic=TEST-TOPIC --command-config client.properties",
                stderr=subprocess.STDOUT,
                shell=True,
                universal_newlines=True,
                env={"JAVA_HOME": "/usr/lib/jvm/java-21-openjdk-amd64"},
            )
            event.set_results({"output": output})
        except subprocess.CalledProcessError as e:
            logger.exception(e.output)
            event.fail()

        return

    def _produce(self, _) -> None:
        uris = None
        security_protocol = "SASL_PLAINTEXT"
        for relation in self.model.relations[REL_NAME_ADMIN]:
            if not relation.app:
                continue

            uris = relation.data[relation.app].get("endpoints", "").split(",")

        username = self.peer_relation.data[self.app]["username"]
        password = self.peer_relation.data[self.app]["password"]

        if not (username and password and uris):
            raise KeyError("missing relation data from app charm")

        client = KafkaClient(
            servers=uris,
            username=username,
            password=password,
            topic="test-topic",
            consumer_group_prefix=None,
            security_protocol=security_protocol,
        )

        client.create_topic()
        client.run_producer()

    def _consume(self, _) -> None:
        uris = None
        security_protocol = "SASL_PLAINTEXT"
        for relation in self.model.relations[REL_NAME_ADMIN]:
            if not relation.app:
                continue

            uris = relation.data[relation.app].get("endpoints", "").split(",")

        username = self.peer_relation.data[self.app]["username"]
        password = self.peer_relation.data[self.app]["password"]

        if not (username and password and uris):
            raise KeyError("missing relation data from app charm")

        client = KafkaClient(
            servers=uris,
            username=username,
            password=password,
            topic="test-topic",
            consumer_group_prefix=None,
            security_protocol=security_protocol,
        )

        client.run_consumer()


if __name__ == "__main__":
    main(ApplicationCharm)
