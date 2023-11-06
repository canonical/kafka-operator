"""Module containing all business logic related to the workload."""

from abc import ABC, abstractmethod
from enum import Enum
from io import IOBase
from typing import Generic, TypeVar, Callable, Sequence

from new.common.workload import User, IOMode
from utils import map_env

T = TypeVar("T", bound=str | IOBase)
V = TypeVar("V", bound=str | IOBase)


class KafkaEntrypoint(str, Enum):
    CONFIG = "configs"
    ACL = "acls"
    LOG_DIR = "log-dirs"
    CMD = "cmd"
    KEYTOOL = "keytool"


class CharmedKafkaPath(Generic[T]):
    def __init__(self, conf_path: str, binaries_path: str, mapper: Callable[[str], T]):
        self.CONF_PATH = conf_path
        self.BINARIES_PATH = binaries_path
        self.mapper = mapper

    def with_mapper(self, mapper: Callable[[str], V]) -> 'CharmedKafkaPath[V]':
        return CharmedKafkaPath(self.CONF_PATH, self.BINARIES_PATH, mapper)

    def _remap(self, name: str) -> T:
        return self.mapper(name)

    @property
    def server_properties(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/server.properties")

    @property
    def client_properties(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/client.properties")

    @property
    def zk_jaas(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/zookeeper-jaas.cfg")

    @property
    def keystore(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/keystore.p12")

    @property
    def server_key(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/server.key")

    @property
    def ca(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/ca.pem")

    @property
    def certificate(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/server.pem")

    @property
    def truststore(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/truststore.jks")

    @property
    def log4j_properties(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/log4j.properties")

    @property
    def jmx_prometheus_javaagent(self) -> T:
        return self.mapper(f"{self.BINARIES_PATH}/jmx_prometheus_javaagent.jar")

    @property
    def jmx_prometheus_config(self) -> T:
        return self.mapper(f"{self.CONF_PATH}/jmx_prometheus.yaml")


class AbstractKafkaService(ABC):

    @abstractmethod
    def start(self):
        """Execute business-logic for starting the workload."""
        ...

    @abstractmethod
    def stop(self):
        """Execute business-logic for stopping the workload."""
        ...

    @abstractmethod
    def health(self) -> bool:
        """Return the health of the service."""
        ...

    @abstractmethod
    def ready(self) -> bool:
        """Check whether the service is ready to be used."""
        ...

    @abstractmethod
    def exec(
            self, command: KafkaEntrypoint, args: Sequence[str] = list(),
            opts: Sequence[str] = list(),
            working_dir: str | None = None
    ): ...

    @abstractmethod
    @property
    def user(self) -> User: ...

    @abstractmethod
    @property
    def paths(self) -> CharmedKafkaPath[str]: ...

    @abstractmethod
    @property
    def read(self) -> CharmedKafkaPath[IOBase]: ...

    @abstractmethod
    @property
    def write(self) -> CharmedKafkaPath[IOBase]: ...

    @abstractmethod
    def get_file(self, filename: str, mode: IOMode) -> IOBase: ...

    def update_environment(self, env: dict[str, str]):
        """Updates /etc/environment file."""
        with self.get_file("/etc/environment", IOMode.READ) as fid:
            existing_env = map_env(fid.read().split("\n"))

        updated_env = existing_env | env

        content = "\n".join([f"{key}={value}" for key, value in updated_env.items()])

        with self.get_file("/etc/environment", IOMode.WRITE) as fid:
            fid.write(content)
