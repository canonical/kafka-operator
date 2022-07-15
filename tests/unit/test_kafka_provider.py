#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from collections import namedtuple

import ops.testing
from ops.charm import CharmBase
from ops.testing import Harness

from kafka_provider import KafkaProvider

ops.testing.SIMULATE_CAN_CONNECT = True

logger = logging.getLogger(__name__)

METADATA = """
    name: kafka
    peers:
        cluster:
            interface: cluster
    provides:
        kafka:
            interface: kafka
"""

CustomRelation = namedtuple("Relation", ["id"])


class DummyKafkaCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.client_relation = KafkaProvider(self)


class TestProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyKafkaCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin_with_initial_hooks()

    @property
    def provider(self):
        return self.harness.charm.client_relation

    def test_relation_config_new_relation_no_password(self):
        self.harness.set_leader(True)
        relation_id = self.harness.add_relation("kafka", "client_app")
        self.harness.update_relation_data(
            self.provider.app_relation.id, "kafka/0", {"private-address": "treebeard"}
        )
        self.harness.add_relation_unit(self.provider.app_relation.id, "kafka/1")
        self.harness.update_relation_data(
            self.provider.app_relation.id, "kafka/1", {"private-address": "shelob"}
        )

        config = self.harness.charm.client_relation.relation_config(
            relation=self.harness.charm.model.get_relation(
                relation_name="kafka", relation_id=relation_id
            )
        )

        self.assertEqual(sorted(["endpoints", "password", "username"]), sorted(config.keys()))
        self.assertEqual(sorted(config["endpoints"].split(",")), ["shelob", "treebeard"])
        self.assertEqual(len(config["password"]), 32)

    def test_relation_config_existing_relation_password(self):
        self.harness.set_leader(True)
        relation_id = self.harness.add_relation("kafka", "client_app")
        self.harness.update_relation_data(
            self.harness.charm.model.get_relation("cluster").id,
            "kafka",
            {"relation-1": "keepitsecret"},
        )
        self.harness.update_relation_data(
            self.provider.app_relation.id, "kafka/0", {"private-address": "treebeard"}
        )

        config = self.harness.charm.client_relation.relation_config(
            relation=self.harness.charm.model.get_relation(
                relation_name="kafka", relation_id=relation_id
            )
        )

        self.assertEqual(config["password"], "keepitsecret")
