#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Basic implementation of an Integrator for MySQL sources."""

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseRequirerData,
    DatabaseRequirerEventHandlers,
)
from kafkacl import BaseConfigFormatter, BaseIntegrator, ConfigOption
from server import SimplePluginServer
from typing_extensions import override


class MySQLConfigFormatter(BaseConfigFormatter):
    """Basic implementation for Aiven JDBC Source connector configuration."""

    # configurable options
    topic_prefix = ConfigOption(json_key="topic.prefix", default="mysql-.*")
    select_mode = ConfigOption(json_key="mode", default="incrementing")
    incrementing_column = ConfigOption(json_key="incrementing.column.name", default="id")

    # non-configurable options
    connector_class = ConfigOption(
        json_key="connector.class",
        default="io.aiven.connect.jdbc.JdbcSourceConnector",
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
    value_converter = ConfigOption(
        json_key="value.converter",
        default="org.apache.kafka.connect.json.JsonConverter",
        configurable=False,
    )


class Integrator(BaseIntegrator):
    """Basic implementation for Kafka Connect MySQL Source Integrator."""

    name = "mysql-source-integrator"
    formatter = MySQLConfigFormatter
    plugin_server = SimplePluginServer

    DB_CLIENT_REL = "data"
    DB_NAME = "test_db"

    def __init__(self, /, charm, plugin_server_args=[], plugin_server_kwargs={}):
        super().__init__(charm, plugin_server_args, plugin_server_kwargs)

        self.database_requirer_data = DatabaseRequirerData(
            self.model, self.DB_CLIENT_REL, self.DB_NAME, extra_user_roles="charmed_dba"
        )
        self.database = DatabaseRequirerEventHandlers(self.charm, self.database_requirer_data)

    @override
    def setup(self) -> None:
        db = self.helpers.fetch_all_relation_data(self.DB_CLIENT_REL)
        self.configure(
            {
                "connection.url": f"jdbc:mysql://{db.get('endpoints')}/{self.DB_NAME}",
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
