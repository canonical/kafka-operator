#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charms.kafka.v0.kafka_snap import ConfigError, KafkaSnap


class TestKafkaSnap(unittest.TestCase):
    def setUp(self):
        self.snap = KafkaSnap()

    @patch('charms.kafka.v0.kafka_snap.SNAP_CONFIG_PATH', "tests/fixtures/")
    def test_get_config_passes_valid_config(self):
        config = self.snap.get_properties("valid_server")
        self.assertNotIn("\n", config.keys())
        self.assertNotIn("#", "".join(list(config.keys())))
        self.assertEqual(len(config), 6)

    def test_get_config_raises_missing_config(self):
        with self.assertRaises(ConfigError):
            self.snap.get_properties("missing")

