#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling operations on Kafka Connect workers."""

import logging
import os
import re
import tempfile
from pathlib import Path
from subprocess import CalledProcessError
from typing import Pattern

import requests
from kafkacl.models import TaskStatus
from requests.auth import HTTPBasicAuth
from tenacity import (
    retry,
    retry_any,
    retry_if_exception,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_fixed,
)

from ..core.connect_models import ConnectContext, HealthResponse
from ..core.literals import GROUP, SUBSTRATE, USER_NAME, ConnectLiterals
from ..core.workload import WorkloadBase

logger = logging.getLogger(__name__)


class PluginDownloadFailedError(Exception):
    """Exception raised when plugin download fails."""


class KafkaClient:
    """Manager for handling Kafka cluster functions."""

    def __init__(self, context: ConnectContext, workload: WorkloadBase):
        self.context = context
        self.workload = workload

    def _parse_bootstrap_servers(self, servers) -> list[tuple[str, int]]:
        """Parses bootstrap servers config entry and returns a list of (host, port) tuples."""
        parsed = []
        for server in servers.split(","):
            parts = server.split(":")
            if len(parts) == 2:
                parsed.append((parts[0], int(parts[1])))
        return parsed

    def health_check(self) -> bool:
        """Checks whether relation to Kafka cluster is healthy or not."""
        if not self.context.kafka_client.ready:
            return False

        # checks whether Apache Kafka cluster is accessible
        for host, port in self._parse_bootstrap_servers(
            self.context.kafka_client.bootstrap_servers
        ):
            if not self.workload.ping(f"{host}:{port}"):
                return False

        return True


class ConnectManager:
    """Manager for functions related to Kafka Connect workers and connector plugins."""

    KAFKA_CLUSTER_ID = "kafka_cluster_id"
    VERSION = "version"
    REQUEST_TIMEOUT = 2

    def __init__(self, context: ConnectContext, workload: WorkloadBase):
        self.context = context
        self.workload = workload
        self._plugins_cache = set()

        self.reload_plugins()

    @property
    def plugins_cache(self) -> set:
        """Local cache of available plugins, populated using checksums of loaded plugins."""
        return self._plugins_cache

    @property
    def plugin_path_initiated(self) -> bool:
        """Checks whether plugin path is initiated or not."""
        return self.workload.dir_exists(self.workload.connect_paths.plugins)

    @property
    def loaded_client_plugins(self) -> set:
        """Returns a set of client usernames for which the client plugin is loaded on this worker."""
        self.reload_plugins()
        cache: set = set()
        for plugin in self.plugins_cache:
            if match := re.search(r"relation-[0-9]+", plugin):
                cache.add(match.group())
        return cache

    @property
    def connectors(self) -> dict[str, TaskStatus]:
        """Returns a mapping of connector names to their status."""
        if not self.healthy:
            return {}

        resp = self._request("GET", "/connectors?expand=status").json()
        # response schema: {connector-name: {status: {connector: {state: STATE}...}...}...}
        return {
            k: TaskStatus(v.get("status", {}).get("connector", {}).get("state", "UNKNOWN"))
            for k, v in resp.items()
        }

    @staticmethod
    def _managed_connector_regex(relation_id: int) -> Pattern:
        """Returns a complied regex pattern matching managed connector names for given `relation_id`.

        Managed connector names should adhere to `.+{RELATION_ID}_{MODEL_UUID}$` regex pattern.
        """
        return re.compile(".+?r" + str(relation_id) + "_[0-9a-f]{32}$")

    def _request(
        self,
        method: str = "GET",
        api: str = "",
        verbose: bool = True,
        **kwargs,
    ) -> requests.Response:
        """Makes a request to Kafka Connect REST endpoint and returns the response.

        Args:
            method (str, optional): HTTP method. Defaults to "GET".
            api (str, optional): Specific Kafka Connect API, e.g. "connector-plugins" or "connectors". Defaults to "".
            verbose (bool, optional): Whether should enable verbose logging or not. Defaults to True.
            kwargs: Keyword arguments which will be passed to `requests.request` method.

        Raises:
            ConnectApiError: If the REST API call is unsuccessful.

        Returns:
            requests.Response: Response object.
        """
        auth = HTTPBasicAuth(
            self.context.peer_workers.ADMIN_USERNAME, self.context.peer_workers.admin_password
        )

        url = f"{self.context.rest_uri}/{api.lstrip('/')}"

        try:
            response = requests.request(
                method, url, verify=False, auth=auth, timeout=self.REQUEST_TIMEOUT, **kwargs
            )
        except Exception as e:
            raise Exception(f"Connect API call /{api} failed: {e}")

        if verbose:
            logging.debug(f"{method} - {url}: {response.content}")

        return response

    def _plugin_checksum(self, plugin_path: Path) -> str:
        """Calculates checksum of a plugin, currently uses SHA-256 algorithm."""
        # Python 3.11+ has hashlib.file_digest(...) method but we use linux utils here for compatibility and better performance.
        raw = self.workload.exec(["sha256sum", str(plugin_path)]).split()
        return raw[0]

    def _create_plugin_dir(self, plugin_path: Path, path_prefix: str = "") -> Path:
        """Creates a unique dir under `PLUGIN_PATH` to better organize lib JAR files."""
        path_prefix_ = f"{path_prefix}-" if path_prefix else ""
        path = (
            Path(self.workload.connect_paths.plugins)
            / f"{path_prefix_}{self._plugin_checksum(plugin_path)}"
        )
        self.workload.mkdir(f"{path}")
        self.workload.exec(["chown", "-R", f"{USER_NAME}:{GROUP}", f"{path}"])
        return path

    def _untar_plugin(self, src_path: Path, dst_path: Path) -> None:
        """UnTARs and decompresses a plugin tarball to the `PLUGIN_PATH` folder."""
        match os.path.splitext(src_path)[-1]:
            case ".gz" | ".tgz":
                opts = "xvzf"
            case ".tar":
                opts = "xvf"
            case _:
                opts = "xvf"

        self.workload.exec(["tar", f"-{opts}", str(src_path), "-C", str(dst_path)])

    def _download_plugin(self, url: str, dst_path: str):
        """Downloads plugin from a given URL and returns the file object."""
        response = requests.get(url, stream=True)
        with open(dst_path, mode="wb") as file:
            for chunk in response.iter_content(chunk_size=10 * 1024):
                file.write(chunk)

    def init_plugin_path(self) -> None:
        """Initiates `PLUGIN_PATH` folder and sets correct ownership and permissions."""
        self.workload.mkdir(self.workload.connect_paths.plugins)
        self.workload.exec(["chmod", "-R", "750", f"{self.workload.connect_paths.plugins}"])
        self.workload.exec(
            ["chown", "-R", f"{USER_NAME}:{GROUP}", f"{self.workload.connect_paths.plugins}"]
        )

    def reload_plugins(self) -> None:
        """Reloads the local `plugins_cache`."""
        try:
            self._plugins_cache = {
                f.name
                for f in self.workload.ls(self.workload.connect_paths.plugins)
                if f.is_dir and not f.name.startswith(".")
            }
        except FileNotFoundError:  # possibly since plugins folder not created yet.
            return

    def load_plugin(self, resource_path: Path, path_prefix: str = "") -> None:
        """Loads a plugin from a given `resource_path` to the `PLUGIN_PATH` folder, skips if previously loaded."""
        if not resource_path.exists():
            logger.info(f"Plugin not yet loaded to {resource_path.name}.")
            return

        if SUBSTRATE == "k8s":
            # we should push the plugin to kafka connect container first.
            tmp_dir = tempfile.mkdtemp()
            tmp_path = f"{tmp_dir}/{os.path.basename(resource_path)}"
            self.workload.write(open(resource_path, "rb"), tmp_path)
            resource_path = Path(tmp_path)

        if self._plugin_checksum(resource_path) in self.plugins_cache:
            logger.debug(f"Plugin {resource_path.name} already loaded, skipping...")
            return

        # the checksum here corresponds to a sha256sum of an empty tar files created using --files-from /dev/null
        # this is what is loaded by default as the connect-plugin resource in Charmhub
        # as Charmhub won't allow charms without a resource
        if self._plugin_checksum(resource_path) == ConnectLiterals.EMPTY_PLUGIN_CHECKSUM:
            logger.debug("Plugin is empty, skipping...")
            return

        load_path = self._create_plugin_dir(resource_path, path_prefix=path_prefix)
        self._untar_plugin(resource_path, load_path)
        self.workload.exec(["chown", "-R", f"{USER_NAME}:{GROUP}", f"{load_path}"])
        self.workload.rmdir(f"{resource_path}")
        self.reload_plugins()
        self.context.worker_unit.should_restart = True

    @retry(
        wait=wait_fixed(2),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(PluginDownloadFailedError),
        reraise=True,
    )
    def load_plugin_from_url(self, plugin_url: str, path_prefix: str = "") -> None:
        """Loads a plugin from a given `plugin_url` to the `PLUGIN_PATH` folder, skips if previously loaded."""
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                path = Path(tmp_dir) / "plugin.tar"
                self._download_plugin(plugin_url, f"{path}")
                self.load_plugin(path, path_prefix=path_prefix)
                logger.debug(f"Plugin {plugin_url} loaded successfully.")
        except CalledProcessError as e:
            if "File exists" in e.stderr:
                logger.debug("Plugin already exists.")
                return
        except Exception as e:
            raise PluginDownloadFailedError(e)

    def remove_plugin(self, path_prefix: str) -> None:
        """Removes plugins for which the plugin-path starts with `path_prefix`."""
        self.workload.remove(
            f"{self.workload.connect_paths.plugins.rstrip('/')}/{path_prefix}*", glob=True
        )

    def _get_health(self) -> requests.Response:
        """Makes a GET request to the unit's Connect API /health Endpoint and returns the response."""
        return self._request("GET", "/health")

    def connector_status(self, relation_id: int) -> TaskStatus:
        """Returns the managed connector status for given `relation_id`."""
        for connector, status in self.connectors.items():
            if re.match(self._managed_connector_regex(relation_id), connector):
                return status

        return TaskStatus.UNKNOWN

    def delete_connector(self, relation_id: int) -> None:
        """Deletes the managed connector instance for given `relation_id`."""
        for connector, _ in self.connectors.items():
            if not re.match(self._managed_connector_regex(relation_id), connector):
                continue

            resp = self._request("DELETE", f"connectors/{connector}")

            if resp.status_code == 204:
                logger.debug(f"Successfully deleted connector for relation ID={relation_id}.")
            else:
                logger.error(f"Unable to delete connector, details: {resp.content}")
                continue

    @property
    @retry(
        wait=wait_fixed(3),
        stop=stop_after_attempt(5),
        retry=retry_any(
            retry_if_result(lambda result: not result), retry_if_exception(lambda _: True)
        ),
        retry_error_callback=lambda _: HealthResponse(status_code=-1),
    )
    def healthy(self) -> HealthResponse:
        """Checks the health of connect service by pinging the Connect API."""
        response = self._get_health()

        if response.status_code in (200, 500, 503):
            return HealthResponse(status_code=response.status_code, **response.json())

        return HealthResponse(status_code=response.status_code)

    def restart_worker(self) -> None:
        """Attempts to restart the connect worker."""
        logger.info("Restarting worker service.")
        self.workload.restart()
