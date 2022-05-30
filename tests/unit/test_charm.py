#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from charms.kafka.v0.kafka_snap import KafkaSnap


class TestKafkaSnap(unittest.TestCase):
    def setUp(self):
        self.snap = KafkaSnap()

    def test_get_config_passes_valid_config(self):
        config = self.snap.get_properties("tests/fixtures/default/valid_server.properties")
        self.assertNotIn("\n", config.keys())
        self.assertNotIn("#", "".join(list(config.keys())))
        self.assertEqual(len(config), 6)

    def test_merge_config_fails_gracefully_on_bad_path(self):
        self.snap.default_config_path = "tests/fixtures/default/"
        self.snap.snap_config_path = "bad/path/"

        self.assertTrue(self.snap.get_merged_properties(property_label="valid_server"))

    def test_merge_config(self):
        self.snap.default_config_path = "tests/fixtures/default/"
        self.snap.snap_config_path = "tests/fixtures/user/"

        config = self.snap.get_merged_properties(property_label="valid_server")
        lines = config.splitlines()
        self.assertEqual(len(lines), 8)
        self.assertIn("default.topic.enable=true", lines)

    def test_get_kafka_apps_succeeds(self):
        self.snap.get_kafka_apps()
        self.snap.install_kafka_snap()

        self.assertTrue(self.snap.get_kafka_apps())
