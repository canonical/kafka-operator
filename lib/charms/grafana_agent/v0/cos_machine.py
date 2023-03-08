#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the cos_machine relation interface."""

import base64
import json
import logging
import lzma
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# FIXME: unify the alert rules format in cosl to drop these ASAP
from charms.loki_k8s.v0.loki_push_api import AlertRules as LogAlerts
from charms.prometheus_k8s.v0.prometheus_scrape import AlertRules as MetricsAlerts
from ops.charm import RelationEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation
from ops.testing import CharmType

LIBID = "1212"  # FIXME: Need to get a valid ID from charmhub
LIBAPI = 0
LIBPATCH = 1

# FIXME: Packing the charm with 2.2.0+139.gd011d92 will produce this error:
# https://chat.charmhub.io/charmhub/pl/bjyt3dahd7y9dcube6nicaxfmc
# PYDEPS = ["cosl"]

DEFAULT_RELATION_NAME = "cos-machine"
DEFAULT_METRICS_ENDPOINT = {
    "path": "/metrics",
    "port": 80,
}

logger = logging.getLogger(__name__)


class COSMachineProvider(Object):
    """Integration endpoint wrapper for the provider side of the cos_machine interface."""

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        metrics_endpoints: Optional[List[dict]] = None,
        metrics_rules_dir: str = "./src/prometheus_alert_rules",
        logs_rules_dir: str = "./src/loki_alert_rules",
        recurse_rules_dirs: bool = False,
        logs_slots: Optional[List[str]] = None,
        dashboard_dirs: Optional[List[str]] = None,
        refresh_events: Optional[List] = None,
    ):
        """Create a COSMachineProvider instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            metrics_endpoints: List of endpoints in the form [{"path": path, "port": port}, ...].
            metrics_rules_dir: Directory where the metrics rules are stored.
            logs_rules_dir: Directory where the logs rules are stored.
            recurse_rules_dirs: Whether or not to recurse into rule paths.
            logs_slots: Snap slots to connect to for scraping logs
                in the form ["snap-name:slot", ...].
            dashboard_dirs: Directory where the dashboards are stored.
            refresh_events: List of events on which to refresh relation data.
        """
        super().__init__(charm, relation_name)
        metrics_endpoints = metrics_endpoints or [DEFAULT_METRICS_ENDPOINT]
        dashboard_dirs = dashboard_dirs or ["./src/grafana_dashboards"]

        self._charm = charm
        self._relation_name = relation_name
        self._metrics_endpoints = metrics_endpoints
        self._metrics_rules = metrics_rules_dir
        self._logs_rules = logs_rules_dir
        self._recursive = recurse_rules_dirs
        self._logs_slots = logs_slots or []
        self._dashboard_dirs = dashboard_dirs
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_refresh)
        self.framework.observe(events.relation_changed, self._on_refresh)
        for event in self._refresh_events:
            self.framework.observe(event, self._on_refresh)

    def _on_refresh(self, event):
        """Trigger the class to update relation data."""
        if isinstance(event, RelationEvent):
            relations = [event.relation]
        else:
            relations = self._charm.model.relations[self._relation_name]

        for relation in relations:
            if relation.data:
                relation.data[self._charm.app].update({"config": self._generate_databag_content()})

    def _generate_databag_content(self) -> str:
        """Collate the data for each nested databag and return it."""
        # The databag is divided in three chunks: metrics, logs, and dashboards.

        data = {
            # primary key
            "metrics": {
                # secondary key
                "scrape_jobs": self._scrape_jobs,
                "alert_rules": self._metrics_alert_rules,
            },
            "logs": {
                "targets": self._logs_slots,
                "alert_rules": self._log_alert_rules,
            },
            "dashboards": {
                "dashboards": self._dashboards,
            },
        }

        return json.dumps(data)

    @property
    def _scrape_jobs(self) -> List[Dict]:
        """Return a prometheus_scrape-like data structure for jobs."""
        job_name_prefix = self._charm.app.name
        return [
            {"job_name": f"{job_name_prefix}_{key}", **endpoint}
            for key, endpoint in enumerate(self._metrics_endpoints)
        ]

    @property
    def _metrics_alert_rules(self) -> Dict:
        """Use (for now) the prometheus_scrape AlertRules to initialize this."""
        alert_rules = MetricsAlerts()
        alert_rules.add_path(self._metrics_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _log_alert_rules(self) -> Dict:
        """Use (for now) the loki_push_api AlertRules to initialize this."""
        alert_rules = LogAlerts()
        alert_rules.add_path(self._logs_rules, recursive=self._recursive)
        return alert_rules.as_dict()

    @property
    def _dashboards(self) -> List[str]:
        dashboards = []
        for d in self._dashboard_dirs:
            for path in Path(d).glob("*"):
                dashboards.append(self._encode_dashboard_content(path.read_bytes()))

        return dashboards

    @staticmethod
    def _encode_dashboard_content(content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = bytes(content, "utf-8")

        return base64.b64encode(lzma.compress(content)).decode("utf-8")


class COSMachineDataChanged(EventBase):
    """Emitted by `COSMachineRequirer` when the provider makes changes to its relation data."""


class COSMachineRequirerEvents(ObjectEvents):
    """`COSMachineRequirer` events."""

    data_changed = EventSource(COSMachineDataChanged)


class COSMachineRequirer(Object):
    """Integration endpoint wrapper for the Requirer side of the cos_machine interface."""

    on = COSMachineRequirerEvents()

    def __init__(
        self,
        charm: CharmType,
        relation_name: str = DEFAULT_RELATION_NAME,
        refresh_events: Optional[List[str]] = None,
    ):
        """Create a COSMachineRequirer instance.

        Args:
            charm: The `CharmBase` instance that is instantiating this object.
            relation_name: The name of the relation to communicate over.
            refresh_events: List of events on which to resfresh relation data.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._refresh_events = refresh_events or [self._charm.on.config_changed]

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_data_changed)
        self.framework.observe(events.relation_changed, self._on_relation_data_changed)
        for event in self._refresh_events:
            self.framework.observe(event, self.trigger_refresh)

    def _on_relation_data_changed(self, _):
        self.on.data_changed.emit()

    def trigger_refresh(self, _):
        """Trigger a refresh of relation data."""
        # FIXME: Figure out what we should do here
        self.on.data_changed.emit()

    @property
    def _relations(self):
        return self._charm.model.relations[self._relation_name]

    @staticmethod
    def _fetch_data_from_relation(relation: Relation, primary_key: str, secondary_key: str):
        """Extract data by path from a relation's app data."""
        # ensure that whatever context we're running this in, we take the necessary precautions:
        if not relation.data or not relation.app:
            return None

        config = json.loads(relation.data[relation.app].get("config", {}))
        return config.get(primary_key, {}).get(secondary_key, None)

    @property
    def metrics_alerts(self) -> Dict[str, Any]:
        """Fetch metrics alerts."""
        alert_rules = {}
        for relation in self._relations:
            if data := self._fetch_data_from_relation(relation, "metrics", "alert_rules"):
                alert_rules.update(data)
        return alert_rules

    @property
    def metrics_jobs(self) -> List[Dict]:
        """Parse the relation data contents and extract the metrics jobs."""
        scrape_jobs = []
        for relation in self._relations:
            if jobs := self._fetch_data_from_relation(relation, "metrics", "scrape_jobs"):
                for job in jobs:
                    job_config = {
                        "job_name": job["job_name"],
                        "metrics_path": job["path"],
                        "static_configs": [{"targets": [f"localhost:{job['port']}"]}],
                    }
                    scrape_jobs.append(job_config)

        return scrape_jobs

    @property
    def logs_alerts(self) -> Dict[str, Any]:
        """Fetch log alerts."""
        alert_rules = {}
        for relation in self._relations:
            if rules := self._fetch_data_from_relation(relation, "logs", "alert_rules"):
                alert_rules.update(rules)
        return alert_rules

    @property
    def dashboards(self) -> List[Dict[str, str]]:
        """Fetch dashboards as encoded content."""
        dashboards = []  # type: List[Dict[str, str]]
        for relation in self._relations:
            if dashboard := self._fetch_data_from_relation(relation, "dashboards", "dashboards"):
                dashboards.append(
                    {
                        "relation_id": str(relation.id),
                        # We don't have the remote charm name, but give us an identifier
                        "charm": f"{relation.name}-{relation.app.name if relation.app else 'unknown'}",
                        "content": self._decode_dashboard_content(dashboard),
                    }
                )
        return dashboards

    @staticmethod
    def _decode_dashboard_content(encoded_content: str) -> str:
        return lzma.decompress(base64.b64decode(encoded_content.encode("utf-8"))).decode()
