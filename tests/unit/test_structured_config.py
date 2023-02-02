
import logging
import unittest
from pathlib import Path

import yaml
from ops.testing import Harness

from charm import KafkaCharm

CONFIG = str(yaml.safe_load(Path("./config.yaml").read_text()))
ACTIONS = str(yaml.safe_load(Path("./actions.yaml").read_text()))
METADATA = str(yaml.safe_load(Path("./metadata.yaml").read_text()))

logger = logging.getLogger(__name__)

class TestStructuredConfig(unittest.TestCase):
    harness = Harness(KafkaCharm, meta=METADATA, config=CONFIG, actions=ACTIONS)

    @classmethod
    def setUpClass(cls) -> None:
        cls.harness.set_model_name("testing")
        cls.harness.begin()

    def setUp(self) -> None:
        # Instantiate the Charmed Operator Framework test harness

        self.addCleanup(self.harness.cleanup)
        self.assertIsInstance(self.harness.charm, KafkaCharm)

    def test_config_parsing_parameters_integer_values(self):
        integer_fields = ["log_flush_offset_checkpoint_interval_ms", "log_segment_bytes", "message_max_bytes", "offsets_topic_num_partitions", "transaction_state_log_num_partitions", "replication_quota_window_num"]
        erroneus_values = [2147483648, -2147483649]
        valid_values = [42, 1000, 1]
        for field in integer_fields:
            self.check_invalid_values(field, erroneus_values)
            self.check_valid_values(field, valid_values)

    def check_valid_values(self, field: str, accepted_values: list):
        """Check the correcteness of the passed values for a field."""
        for value in accepted_values:
            self.harness.update_config({field: value})
            self.assertEqual(self.harness.charm.config[field], value)

    def check_invalid_values(self, field: str, erroneus_values: list):
        """Check the incorrectness of the passed values for a field."""
        for value in erroneus_values:
            self.harness.update_config({field: value})
            self.assertRaises(ValueError, lambda: self.harness.charm.config)
    
    def test_product_related_values(self):
        """Test specific parameters for each field."""
        # log_message_timestamp_type field
        erroneus_values = ["test-value", "CreateTimes", "foo", "bar"]

        self.check_invalid_values("log_message_timestamp_type", erroneus_values)
        accepted_values = ["CreateTime", "LogAppendTime"]
        self.check_valid_values("log_message_timestamp_type", accepted_values)
       
        # log_cleanup_policy field
        self.check_invalid_values("log_cleanup_policy", erroneus_values)
        accepted_values = ["compact", "delete"]
        self.check_valid_values("log_cleanup_policy", accepted_values)

        # compression_type field
        self.check_invalid_values("compression_type", erroneus_values)
        accepted_values = ['gzip', 'snappy', 'lz4', 'zstd' 'uncompressed', 'producer']
        self.check_valid_values("compression_type", accepted_values)

    def test_values_gt_zero(self):
        """Check fields greater than zero."""
        gt_zero_fields = ["log_flush_interval_messages"]
        erroneus_values = [0, -2147483649, -34]
        valid_values = [42, 1000, 1]
        for field in gt_zero_fields:
            self.check_invalid_values(field, erroneus_values)
            self.check_valid_values(field, valid_values)
    
    def test_values_gteq_zero(self):
        """Check fields greater or equal than zero."""
        gteq_zero_fields = ["replication_quota_window_num", "log_segment_bytes", "message_max_bytes"]
        erroneus_values = [-2147483649, -34]
        valid_values = [42, 1000, 1, 0]
        for field in gteq_zero_fields:
            self.check_invalid_values(field, erroneus_values)
            self.check_valid_values(field, valid_values)

    def test_values_in_specific_intervals(self):
        """Check fields on prefdefined intervals."""
        # "log_flush_interval_ms"
        erroneus_values = [0, -1, 1000*60*60 + 1]
        valid_values = [42, 1000, 10000, 1]
        self.check_invalid_values("log_flush_interval_ms", erroneus_values)
        self.check_valid_values("log_flush_interval_ms", valid_values)

        # "log_cleaner_delete_retention_ms"
        erroneus_values = [-1 , 0, 1000*60*60*24*90 + 1]
        valid_values = [42, 1000, 10000, 1, 1000*60*60*24*90]
        self.check_invalid_values("log_cleaner_delete_retention_ms", erroneus_values)
        self.check_valid_values("log_cleaner_delete_retention_ms", valid_values)

        # "log_cleaner_min_compaction_lag_ms"
        erroneus_values = [-1, 1000*60*60*24*7 + 1]
        valid_values = [42, 1000, 10000, 1, 1000*60*60*24*7]
        self.check_invalid_values("log_cleaner_min_compaction_lag_ms", erroneus_values)
        self.check_valid_values("log_cleaner_min_compaction_lag_ms", valid_values)

        partititions_fields = ["transaction_state_log_num_partitions","offsets_topic_num_partitions"]
        erroneus_values = [10001, -1]
        valid_values = [42, 1000, 10000, 1]
        for field in partititions_fields:
            self.check_invalid_values(field, erroneus_values)
            self.check_valid_values(field, valid_values)
