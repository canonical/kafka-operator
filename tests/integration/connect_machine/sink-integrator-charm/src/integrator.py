#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Basic implementation of an Integrator for PostgreSQL."""

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseRequirerData,
    DatabaseRequirerEventHandlers,
)
from kafkacl import BaseConfigFormatter, BaseIntegrator, ConfigOption
from server import SimplePluginServer
from typing_extensions import override


class PostgresConfigFormatter(BaseConfigFormatter):
    """Basic implementation for Aiven JDBC Sink connector configuration."""

    # configurable options
    topics_regex = ConfigOption(json_key="topics.regex", default="postgres-.*")
    insert_mode = ConfigOption(json_key="insert.mode", default="insert")

    # non-configurable options
    connector_class = ConfigOption(
        json_key="connector.class",
        default="io.aiven.connect.jdbc.JdbcSinkConnector",
        configurable=False,
    )
    topic_partitions = ConfigOption(
        json_key="topic.creation.default.partitions", default=10, configurable=False
    )
    topic_replication_factor = ConfigOption(
        json_key="topic.creation.default.replication.factor", default=-1, configurable=False
    )
    tasks_max = ConfigOption(json_key="tasks.max", default=1, configurable=False)
    auto_create = ConfigOption(json_key="auto.create", default=True, configurable=False)
    auto_evolve = ConfigOption(json_key="auto.evolve", default=True, configurable=False)
    pk_mode = ConfigOption(json_key="pk.mode", default="none", configurable=False)
    key_converter = ConfigOption(
        json_key="key.converter",
        default="org.apache.kafka.connect.storage.StringConverter",
        configurable=False,
    )
    value_converter = ConfigOption(
        json_key="value.converter",
        default="org.apache.kafka.connect.json.JsonConverter",
        configurable=False,
    )


class Integrator(BaseIntegrator):
    """Basic implementation for Kafka Connect PostgreSQL Sink Integrator."""

    name = "postgres-sink-integrator"
    formatter = PostgresConfigFormatter
    plugin_server = SimplePluginServer

    DB_CLIENT_REL = "data"
    DB_NAME = "sink_db"

    def __init__(self, /, charm, plugin_server_args=[], plugin_server_kwargs={}):
        super().__init__(charm, plugin_server_args, plugin_server_kwargs)

        self.database_requirer_data = DatabaseRequirerData(
            self.model, self.DB_CLIENT_REL, self.DB_NAME, extra_user_roles="admin"
        )
        self.database = DatabaseRequirerEventHandlers(self.charm, self.database_requirer_data)

    @override
    def setup(self) -> None:
        db = self.helpers.fetch_all_relation_data(self.DB_CLIENT_REL)
        self.configure(
            {
                "connection.url": f"jdbc:postgresql://{db.get('endpoints')}/{self.DB_NAME}",
                "connection.user": db.get("username"),
                "connection.password": db.get("password"),
            }
        )

    @override
    def teardown(self):
        pass

    @property
    @override
    def ready(self):
        return self.helpers.check_data_interfaces_ready([self.DB_CLIENT_REL])
