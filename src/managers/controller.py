#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling KRaft Controller."""

import logging
import os
from subprocess import CalledProcessError

from ops.pebble import ExecError
from tenacity import retry, stop_after_attempt, wait_fixed

from core.cluster import ClusterState
from core.workload import WorkloadBase
from literals import GROUP, KRAFT_VERSION, USER_ID, KRaftQuorumInfo, KRaftUnitStatus

logger = logging.getLogger(__name__)


class ControllerManager:
    """Manager for handling KRaft controller functions."""

    def __init__(self, state: ClusterState, workload: WorkloadBase):
        self.state = state
        self.workload = workload

    @staticmethod
    def _parse_lag_col(_str: str) -> int:
        """Parses the lag column from metadata-quorum output, returns -1 if unsuccessful."""
        try:
            return int(_str)
        except (ValueError, TypeError):
            return -1

    def format_storages(
        self,
        uuid: str,
        internal_user_credentials: dict[str, str] | None = None,
        kraft_version: int = KRAFT_VERSION,
        initial_controllers: str | None = None,
    ) -> None:
        """Use a passed uuid to format storages."""
        # NOTE data dirs have changed permissions by storage_attached hook. For some reason
        # storage command bin needs these locations to be root owned. Momentarily raise permissions
        # during the format phase.
        self.workload.exec(["chown", "-R", "root:root", f"{self.workload.paths.data_path}"])

        command = [
            "format",
            "--ignore-formatted",
            "--cluster-id",
            uuid,
            "-c",
            self.workload.paths.server_properties,
        ]

        if kraft_version > 0:
            command.append("--feature")
            command.append(f"kraft.version={kraft_version}")

            if initial_controllers:
                command.append("--initial-controllers")
                command.append(initial_controllers)
            else:
                command.append("--standalone")

        if internal_user_credentials:
            for user, password in internal_user_credentials.items():
                command += ["--add-scram", f"SCRAM-SHA-512=[name={user},password={password}]"]
        self.workload.run_bin_command(bin_keyword="storage", bin_args=command)

        # Drop permissions again for the main process
        self.workload.exec(["chmod", "-R", "750", f"{self.workload.paths.data_path}"])
        self.workload.exec(
            ["chown", "-R", f"{USER_ID}:{GROUP}", f"{self.workload.paths.data_path}"]
        )

    def generate_uuid(self) -> str:
        """Generate UUID using `kafka-storage.sh` utility."""
        uuid = self.workload.run_bin_command(
            bin_keyword="storage", bin_args=["random-uuid"]
        ).strip()
        return uuid

    def get_metadata_directory_id(self, log_dirs: str) -> str:
        """Read directory.id from meta.properties file in the metadata logs dir."""
        raw = self.workload.read(os.path.join(log_dirs, "meta.properties"))
        for line in raw:
            if line.startswith("directory.id"):
                return line.strip().replace("directory.id=", "")

        return ""

    @retry(
        wait=wait_fixed(15),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def add_controller(self, bootstrap_node: str) -> str:
        """Adds current unit to the dynamic quorum in KRaft mode.

        Returns:
            the added unit's metadata_directory_id if successful.
        """
        try:
            result = self.workload.run_bin_command(
                bin_keyword="metadata-quorum",
                bin_args=[
                    "--bootstrap-controller",
                    bootstrap_node,
                    "--command-config",
                    self.workload.paths.kraft_client_properties,
                    "add-controller",
                ],
            )
            logger.debug(result)
        except (CalledProcessError, ExecError) as e:
            error_details = f"{e.stdout} {e.stderr}"
            if "DuplicateVoterException" not in error_details:
                raise e

        metadata_directory_id = self.get_metadata_directory_id(self.state.metadata_log_dir)
        return metadata_directory_id

    @retry(
        wait=wait_fixed(10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def remove_controller(
        self,
        controller_id: int,
        controller_metadata_directory_id: str,
        bootstrap_node: str | None = None,
    ):
        """Removes a controller with specified controller_id and metadata_directory_id from KRaft dynamic quorum."""
        if not bootstrap_node:
            bootstrap_node = self.state.cluster.bootstrap_controller

        try:
            self.workload.run_bin_command(
                bin_keyword="metadata-quorum",
                bin_args=[
                    "--bootstrap-controller",
                    bootstrap_node,
                    "--command-config",
                    self.workload.paths.kraft_client_properties,
                    "remove-controller",
                    "--controller-id",
                    str(controller_id),
                    "--controller-directory-id",
                    controller_metadata_directory_id,
                ],
            )
        except (CalledProcessError, ExecError) as e:
            error_details = f"{e.stdout} {e.stderr}"
            if "VoterNotFoundException" in error_details or "TimeoutException" in error_details:
                # successful
                return
            raise e

    def quorum_status(self) -> dict[int, KRaftQuorumInfo]:
        """Returns a mapping of controller id to KRaftQuorumInfo."""
        bootstrap_controller = self.state.peer_cluster.bootstrap_controller
        if not bootstrap_controller:
            return {}

        if not self.workload.ping(bootstrap_controller):
            return {}

        try:
            result = self.workload.run_bin_command(
                bin_keyword="metadata-quorum",
                bin_args=[
                    "--bootstrap-controller",
                    bootstrap_controller,
                    "--command-config",
                    self.workload.paths.kraft_client_properties,
                    "describe",
                    "--replication",
                ],
            )
        except (CalledProcessError, ExecError) as e:
            error_details = f"{e.stdout} {e.stderr}"
            logger.error(error_details)
            return {}

        status: dict[int, KRaftQuorumInfo] = {}
        for line in result.split("\n"):
            fields = [c.strip() for c in line.split("\t")]
            try:
                status[int(fields[0])] = KRaftQuorumInfo(
                    directory_id=fields[1],
                    lag=self._parse_lag_col(fields[3]),
                    status=KRaftUnitStatus(fields[6]),
                )
            except (ValueError, IndexError):
                continue

        logger.debug(f"Latest quorum status: {status}")
        return status

    def broker_active(self) -> bool:
        """Checks if broker id is recognised as active by the controller. This is a live check."""
        quorum_status = self.quorum_status()
        broker_id = self.state.unit_broker.broker_id

        if broker_id not in quorum_status:
            return False

        expected_statuses = (
            (KRaftUnitStatus.LEADER, KRaftUnitStatus.FOLLOWER)
            if self.state.runs_controller
            else (KRaftUnitStatus.OBSERVER,)
        )

        return all(
            [
                quorum_status[broker_id].status in expected_statuses,
                quorum_status[broker_id].lag >= 0,
            ]
        )
