from new.config import ServerConfig
from new.core.models import ZookeeperConfig
from new.core.workload import AbstractKafkaService
from new.managers.auth import KafkaAuth

class ZookeeperManager:

    INTER_BROKER_USER = "sync"
    ADMIN_USER = "admin"

    INTERNAL_USERS = [INTER_BROKER_USER, ADMIN_USER]

    def __init__(self,
                 config: ZookeeperConfig,
                 auth: KafkaAuth,
                 workload: AbstractKafkaService
                 ):
        self.config = config
        self.workload = workload
        self.auth = auth

    def set_zk_jaas_config(self) -> None:
        """Writes the ZooKeeper JAAS config using ZooKeeper relation data."""
        jaas_config = f"""
            Client {{
                org.apache.zookeeper.server.auth.DigestLoginModule required
                username="{self.config.username}"
                password="{self.config.password}";
            }};
        """

        with self.workload.write.zk_jaas as fid:
            fid.write(jaas_config)

    def set_server_properties(self, server_config: ServerConfig) -> None:
        """Writes all Kafka config properties to the `server.properties` path."""
        with self.workload.write.server_properties as fid:
            fid.write(server_config.server_properties)

    def create_internal_credentials(self) -> list[tuple[str, str]]:
        """Creates internal SCRAM users during cluster start.

        Returns:
            List of (username, password) for all internal users


        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """
        credentials = [
            (username, self.auth.generate_password()) for username in self.INTERNAL_USERS
        ]
        for username, password in credentials:
            self.update_internal_user(username=username, password=password)

        return credentials

    def update_internal_user(self, username: str, password: str) -> None:
        """Updates internal SCRAM usernames and passwords.

        Raises:
            RuntimeError if called from non-leader unit
            KeyError if attempted to update non-leader unit
            subprocess.CalledProcessError if command to ZooKeeper failed
        """

        if username not in self.INTERNAL_USERS:
            raise KeyError(
                f"Can only update internal charm users: {self.INTERNAL_USERS}, not {username}."
            )

        # do not start units until SCRAM users have been added to ZooKeeper for server-server auth
        self.auth.add_user(
            username=username,
            password=password,
            zk_auth=True,
        )


