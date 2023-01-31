from pydantic import BaseModel, ValidationError, validator

class CharmConfig(BaseModel):
    offsets_retention_minutes: int
    auto_create_topics: bool
    compression_type: str
    log_flush_interval_messages: int # long
    log_flush_interval_ms: int # long
    log_flush_offset_checkpoint_interval_ms: int
    log_retention_bytes: int #long
    log_retention_ms: int #long
    log_segment_bytes: int
    message_max_bytes: int
    offsets_topic_num_partitions: int
    transaction_state_log_num_partitions: int
    unclean_leader_election_enable: bool
    log_cleaner_delete_retention_ms: int #long
    log_cleaner_min_compaction_lag_ms: int #long
    log_cleanup_policy: str
    log_message_timestamp_type: str
    ssl_cipher_suites: str
    replication_quota_window_num: int
    zookeeper_ssl_cipher_suites: str



    validator("log_message_timestamp_type")
    @classmethod
    def log_message_timestamp_type_validator(cls, value: str):
        accepted_values = ["CreateTime","LogAppendTime"]
        if value not in accepted_values:
            return ValueError(f"Value out of the accepted values: {accepted_values}")
        return value

    @validator("log_cleanup_policy")
    @classmethod
    def log_cleanup_policy_validator(cls, value:str):
        accepted_values = ["compact", "delete"]
        if value not in accepted_values:
            return ValueError(f"Value out of the accepted values: {accepted_values}")
        return value

    @validator("log_cleaner_min_compaction_lag_ms")
    @classmethod
    def log_cleaner_min_compaction_lag_ms_validator(cls, value:int):
        if value >= 0 and value <= 1000*60*60*24*7:
            return value
        return ValueError("Value of of range.")
    
    @validator("log_cleaner_delete_retention_ms")
    @classmethod
    def log_cleaner_delete_retention_ms_validator(cls, value: int):
        if value > 0 and value <= 1000*60*60*24*90:
            return value
        return ValueError("Value of of range.")

    @validator("offsets_topic_num_partitions")
    @validator("transaction_state_log_num_partitions")
    @classmethod
    def between_zero_and_10k(cls, value: int):
        if value >= 0 and value <= 10000:
            return value
        return ValueError("Value below zero or greater than 10000.")

    @validator("log_retention_ms")
    @validator("log_retention_bytes")
    @classmethod
    def greater_minus_one(cls, value: int):
        if value < -1:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return value

    @validator("log_flush_interval_messages")
    @classmethod
    def greater_than_one(cls, value: int):
        if value < 1:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return value

    @validator("log_flush_interval_ms")
    @classmethod
    def flush_interval(cls, value: int):
        #1-(1000*60*60)
        if value > 0 or value <=1000*60*60:
            return value
        return ValueError("Value out of range")
    
    @validator("log_segment_bytes")
    @validator("message_max_bytes")
    @validator("replication_quota_window_num")
    @classmethod
    def greater_than_zero(cls, value: int):
        if value < 0:
            raise ValueError("Value below -1. Accepted value are greater or equal than -1.")
        return value
    
    @validator("compression_type")
    @classmethod
    def value_compression_type(cls, value:str):
        accepted_values = ['gzip', 'snappy', 'lz4', 'zstd' 'uncompressed', 'producer']
        if value not in accepted_values:
            raise 
        return value
