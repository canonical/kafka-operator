#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from ops.testing import Harness

from charm import KafkaCharm
from kafka_helpers import get_config, merge_config


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(KafkaCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.charm = self.harness.charm

    def test_get_config_passes_valid_config(self):
        config = get_config("tests/fixtures/valid_server.properties")
        assert "\n" not in config.keys()
        assert "#" not in "".join(list(config.keys()))
        assert len(config) == 6

    def test_merge_config_fails_gracefully_on_bad_path(self):
        assert merge_config(
            default="tests/fixtures/valid_server.properties", override="/tmp/badpath"
        )

    def test_merge_config(self):
        config = merge_config(
            default="tests/fixtures/valid_server.properties",
            override="tests/fixtures/valid_server_user.properties",
        )
        lines = config.splitlines()
        assert len(lines) == 8
        assert "default.topic.enable=true" in lines
