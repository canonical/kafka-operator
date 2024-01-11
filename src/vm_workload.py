#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""KafkaSnap class and methods."""

import logging
import os
import re
import secrets
import shutil
import string
import subprocess
from typing import Dict, List

from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import snap
from tenacity import retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

from core.literals import CHARMED_KAFKA_SNAP_REVISION, PATHS, SNAP_NAME
from core.workload import PathsBase, WorkloadBase

logger = logging.getLogger(__name__)


class KafkaPaths(PathsBase):
    """Object to store common paths for Kafka."""
    def __init__(self):
        conf_path = PATHS["CONF"]
        data_path = PATHS["DATA"]
        binaries_path = PATHS["BIN"]
        logs_path = PATHS["LOGS"]
        super().__init__(conf_path, logs_path, data_path, binaries_path)

    @property
    def server_properties(self):
        return f"{self.conf_path}/server.properties"

    @property
    def client_properties(self):
        return f"{self.conf_path}/client.properties"

    @property
    def zk_jaas(self):
        return f"{self.conf_path}/zookeeper-jaas.cfg"

    @property
    def keystore(self):
        return f"{self.conf_path}/keystore.p12"

    @property
    def truststore(self):
        return f"{self.conf_path}/truststore.jks"

    @property
    def log4j_properties(self):
        return f"{self.conf_path}/log4j.properties"

    @property
    def jmx_prometheus_javaagent(self):
        return f"{self.binaries_path}/jmx_prometheus_javaagent.jar"

    @property
    def jmx_prometheus_config(self):
        return f"{self.conf_path}/jmx_prometheus.yaml"


class KafkaWorkload(WorkloadBase):
    """Wrapper for performing common operations specific to the Kafka Snap."""

    # FIXME: Paths and constants integrated into WorkloadBase?
    SNAP_NAME = "charmed-kafka"
    SNAP_SERVICE = "daemon"
    LOG_SLOT = "logs"

    def __init__(self) -> None:
        self.paths = KafkaPaths()
        self.kafka = snap.SnapCache()[SNAP_NAME]

    def start(self) -> None:
        try:
            self.kafka.start(services=[self.SNAP_SERVICE])
        except snap.SnapError as e:
            logger.exception(str(e))

    def stop(self) -> None:
        try:
            self.kafka.stop(services=[self.SNAP_SERVICE])
        except snap.SnapError as e:
            logger.exception(str(e))

    def restart(self) -> None:
        try:
            self.kafka.restart(services=[self.SNAP_SERVICE])
        except snap.SnapError as e:
            logger.exception(str(e))

    def read(self, path: str) -> List[str]:
        if not os.path.exists(path):
            return []
        else:
            with open(path) as f:
                content = f.read().split("\n")

        return content

    def write(self, content: str, path: str, mode: str = "w") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(content)

        self.set_snap_ownership(path=path)

    def exec(self, command: str, env: str = "", working_dir: str | None = None) -> str:
        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                shell=True,
                cwd=working_dir,
            )
            logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    @retry(
    wait=wait_fixed(1),
    stop=stop_after_attempt(5),
    retry_error_callback=lambda state: state.outcome.result(),  # type: ignore
    retry=retry_if_not_result(lambda result: True if result else False),
    )
    def active(self) -> bool:
        try:
            return bool(self.kafka.services[self.SNAP_SERVICE]["active"])
        except KeyError:
            return False

    def install(self) -> bool:
        """Loads the Kafka snap from LP.

        Returns:
            True if successfully installed. False otherwise.
        """
        try:
            apt.update()
            apt.add_package(["snapd"])
            cache = snap.SnapCache()
            kafka = cache[SNAP_NAME]

            kafka.ensure(snap.SnapState.Present, revision=CHARMED_KAFKA_SNAP_REVISION)

            self.kafka = kafka
            self.kafka.connect(plug="removable-media")

            self.kafka.hold()

            return True
        except (snap.SnapError, apt.PackageNotFoundError) as e:
            logger.error(str(e))
            return False

    def disable_enable(self) -> None:
        """Disables then enables snap service.

        Necessary for snap services to recognise new storage mounts

        Raises:
            subprocess.CalledProcessError if error occurs
        """
        subprocess.run(f"snap disable {self.SNAP_NAME}", shell=True)
        subprocess.run(f"snap enable {self.SNAP_NAME}", shell=True)

    def get_service_pid(self) -> int:
        """Gets pid of a currently active snap service.

        Returns:
            Integer of pid

        Raises:
            SnapError if error occurs or if no pid string found in most recent log
        """
        java_processes = subprocess.check_output(
            "pidof java", stderr=subprocess.PIPE, universal_newlines=True, shell=True
        )

        logger.debug(f"Java processes: {java_processes}")

        for pid in java_processes.split():
            with open(f"/proc/{pid}/cgroup", "r") as fid:
                content = "".join(fid.readlines())

                if f"{self.SNAP_NAME}.{self.SNAP_SERVICE}" in content:
                    logger.debug(
                        f"Found Snap service {self.SNAP_SERVICE} for {self.SNAP_NAME} with PID {pid}"
                    )
                    return int(pid)

        raise snap.SnapError(f"Snap {self.SNAP_NAME} pid not found")

    def run_bin_command(self, bin_keyword: str, bin_args: List[str], opts: List[str] = []) -> str:
        """Runs kafka bin command with desired args.

        Args:
            bin_keyword: the kafka shell script to run
                e.g `configs`, `topics` etc
            bin_args: the shell command args
            opts: any additional opts args strings

        Returns:
            String of kafka bin command output

        Raises:
            `subprocess.CalledProcessError`: if the error returned a non-zero exit code
        """
        opts_str = " ".join(opts)
        bin_str = " ".join(bin_args)
        command =  f"{opts_str} {SNAP_NAME}.{bin_keyword} {bin_str}"
        return self.exec(command)

    def update_environment(self, env: Dict[str, str]) -> None:
        """Updates /etc/environment file."""
        updated_env = self.get_env() | env
        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])
        self.write(content=content, path="/etc/environment", mode="w")

    @staticmethod
    def set_snap_ownership(path: str) -> None:
        """Sets a filepath `snap_daemon` ownership."""
        shutil.chown(path, user="snap_daemon", group="root")

        for root, dirs, files in os.walk(path):
            for fp in dirs + files:
                shutil.chown(os.path.join(root, fp), user="snap_daemon", group="root")

    @staticmethod
    def set_snap_mode_bits(path: str) -> None:
        """Sets filepath mode bits."""
        os.chmod(path, 0o770)

        for root, dirs, files in os.walk(path):
            for fp in dirs + files:
                os.chmod(os.path.join(root, fp), 0o770)

    @staticmethod
    def map_env(env: list[str]) -> dict[str, str]:
        """Builds environment map for arbitrary env-var strings.

        Returns:
            Dict of env-var and value
        """
        map_env = {}
        for var in env:
            key = "".join(var.split("=", maxsplit=1)[0])
            value = "".join(var.split("=", maxsplit=1)[1:])
            if key:
                # only check for keys, as we can have an empty value for a variable
                map_env[key] = value

        return map_env

    def get_env(self) -> dict[str, str]:
        """Builds map of current basic environment for all processes.

        Returns:
            Dict of env-var and value
        """
        raw_env = self.read("/etc/environment")
        return self.map_env(env=raw_env)

    @staticmethod
    def generate_password() -> str:
        """Creates randomized string for use as app passwords.

        Returns:
            String of 32 randomized letter+digit characters
        """
        return "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(32)])
