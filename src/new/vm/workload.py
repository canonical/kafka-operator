import subprocess
from functools import cached_property
from io import TextIOWrapper
from typing import cast, Sequence, List

from .health import KafkaHealth
from ..common.vm import SnapService
from ..common.workload import IOMode, User
from new.core.models import CharmState
from ..utils import WithLogging
from new.core.workload import AbstractKafkaService, KafkaEntrypoint
from new.core.workload import CharmedKafkaPath


class KafkaService(AbstractKafkaService, WithLogging):
    """Class representing Workload implementation for Spark History server on K8s."""

    def __init__(
            self, charm_state: CharmState, snap: SnapService, kafka_paths: CharmedKafkaPath[str]
    ) -> None:
        self.snap = snap
        self.charm_state = charm_state
        self.kafka_paths = kafka_paths
        self.cluster = self.charm_state.cluster
        self.charm_config = self.charm_state.config
        self.kafka_clients = self.charm_state.clients

        self._health_checker = KafkaHealth(
            self.charm_config, self.kafka_clients, self.snap, self.kafka_paths, self.cluster
        )

    def get_file(self, filename: str, mode: IOMode) -> TextIOWrapper:
        match mode:
            case IOMode.READ:
                return cast(open(filename, "r"), TextIOWrapper)
            case IOMode.WRITE:
                return cast(open(filename, "w"), TextIOWrapper)
        raise ValueError(f"mode provided {mode} not allowed")

    @cached_property
    def user(self) -> User:
        return User("snap_daemon", "root")

    @cached_property
    def paths(self):
        return self.kafka_paths

    @cached_property
    def read(self):
        return self.kafka_paths.with_mapper(
            lambda filename: self.get_file(filename, IOMode.READ)
        )

    @cached_property
    def write(self):
        return self.kafka_paths.with_mapper(
            lambda filename: self.get_file(filename, IOMode.WRITE)
        )

    def start(self):
        if not self.snap.active or not self.snap.get_service_pid():
            self.snap.install()
            self.snap.start_snap_service()
        else:
            self.snap.restart_snap_service()

    def stop(self):
        self.snap.stop_snap_service()

    def _run_command(
            self, args: List[str], working_dir: str | None = None
    ) -> str:
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
        try:
            output = subprocess.check_output(
                " ".join(args), stderr=subprocess.PIPE, universal_newlines=True, shell=True,
                cwd=working_dir
            )
            self.logger.debug(f"{output=}")
            return output
        except subprocess.CalledProcessError as e:
            self.logger.debug(f"cmd failed - cmd={e.cmd}, stdout={e.stdout}, stderr={e.stderr}")
            raise e

    def exec(
            self, command: KafkaEntrypoint, args: Sequence[str] = list(),
            opts: Sequence[str] = list(),
            working_dir: str | None = None
    ):
        match command:
            case KafkaEntrypoint.CMD.value:
                self._run_command(list(args), working_dir=working_dir)
            case _:
                self.snap.run_bin_command(command.value, list(args), list(opts))

    def health(self) -> bool:
        return (
                self.ready() and self.snap.active and
                self._health_checker.machine_configured()
        )

    def ready(self) -> bool:
        return self.charm_state.ready_to_start
