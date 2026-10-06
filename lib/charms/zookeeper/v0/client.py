#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""ZooKeeperManager and ZooKeeperClient classes

`ZooKeeperManager` provides an interface for performing actions that requires 
a connection to the current ZK quorum leader, e.g updating zNodes, ACLs and quorum members.
On `__init__`, it loops through all passed hosts, attempts a `ZooKeeperClient` connection, and 
checks leadership of each unit, storing the current quorum leader host as an attribute.

In most cases, custom `Exception`s raised by `ZooKeeperManager` should trigger an `event.defer()`,
as they indicate that the servers are not ready to have actions performed upon them just yet.

`ZooKeeperClient` serves as a handler for managing a ZooKeeper client connection to a
single unit. It's methods contain common 4lw commands, and functionality to read/write
to specific zNodes.
It is not expected to use this class from directly from charm code,
but to instead use the `ZooKeeperManager` class to perform it's actions on the ZK servers.


Instances of `ZooKeeperManager` are to be created by methods in either the `Charm` itself,
or from another library.

Example usage for `ZooKeeperManager`:

```python

def update_cluster(new_members: List[str], event: EventBase) -> None:
    
    try:
        zk = ZooKeeperManager(
            hosts=["10.141.73.20", "10.141.73.21"],
            client_port=2181,
            username="super",
            password="password"
        )
        
        current_quorum_members = zk.server_members

        servers_to_remove = list(current_quorum_members - new_members)
        zk.remove_members(servers_to_remove)
        
        servers_to_add = sorted(new_members - current_quorum_members)
        zk.add_members(servers_to_add)

    except (
        MembersSyncingError,
        MemberNotReadyError,
        QuorumLeaderNotFoundError,
    ) as e:
        logger.info(str(e))
        event.defer()
        return
```
"""

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from kazoo.client import ACL, KazooClient
from kazoo.handlers.threading import KazooTimeoutError
from tenacity import RetryError, retry
from tenacity.retry import retry_if_not_result
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_fixed

# The unique Charmhub library identifier, never change it
LIBID = "4dc4430e6e5d492699391f57bd697fce"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 8


logger = logging.getLogger(__name__)

# Kazoo logs are unbearably chatty
logging.getLogger("kazoo.client").disabled = True


class MembersSyncingError(Exception):
    """Generic exception for when quorum members are syncing data."""

    pass


class MemberNotReadyError(Exception):
    """Generic exception for when a zk unit can't be connected to or is not broadcasting."""

    pass


class QuorumLeaderNotFoundError(Exception):
    """Generic exception for when there are no zk leaders in the app."""

    pass


class NoUnitFoundError(Exception):
    """Generic exception for when there are no running zk unit in the app."""

    pass


class ZooKeeperManager:
    """Handler for performing ZK commands."""

    def __init__(
        self,
        hosts: List[str],
        username: str,
        password: str,
        client_port: int = 2181,
        use_ssl: bool = False,
        keyfile_path: Optional[str] = "",
        keyfile_password: Optional[str] = "",
        certfile_path: Optional[str] = "",
        read_only: bool = True,
    ):
        self.hosts = hosts
        self.username = username
        self.password = password
        self.client_port = client_port
        self.use_ssl = use_ssl
        self.keyfile_path = keyfile_path
        self.keyfile_password = keyfile_password
        self.certfile_path = certfile_path
        self.zk_host = ""
        self.read_only = read_only

        if not read_only:
            try:
                self.zk_host = self.get_leader()
            except RetryError:
                raise QuorumLeaderNotFoundError("quorum leader not found")

        else:
            try:
                self.zk_host = self.get_any_unit()

            except RetryError:
                raise NoUnitFoundError

    @retry(
        wait=wait_fixed(3),
        stop=stop_after_attempt(2),
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def get_leader(self) -> str:
        """Attempts to find the current ZK quorum leader.

        In the case when there is a leadership election, this may fail.
        When this happens, we attempt 1 retry after 3 seconds.

        Returns:
            String of the host for the quorum leader

        Raises:
            tenacity.RetryError: if the leader can't be found during the retry conditions
        """
        leader = None
        for host in self.hosts:
            try:
                with ZooKeeperClient(
                    host=host,
                    client_port=self.client_port,
                    username=self.username,
                    password=self.password,
                    use_ssl=self.use_ssl,
                    keyfile_path=self.keyfile_path,
                    keyfile_password=self.keyfile_password,
                    certfile_path=self.certfile_path,
                ) as zk:
                    response = zk.srvr
                    if response.get("Mode") == "leader":
                        leader = host
                        break
            except KazooTimeoutError:  # in the case of having a dead unit in relation data
                logger.debug(f"TIMEOUT - {host}")
                continue

        return leader or ""

    @retry(
        wait=wait_fixed(3),
        stop=stop_after_attempt(2),
        retry=retry_if_not_result(lambda result: True if result else False),
    )
    def get_any_unit(self) -> str:
        any_host = None
        for host in self.hosts:
            try:
                with ZooKeeperClient(
                    host=host,
                    client_port=self.client_port,
                    username=self.username,
                    password=self.password,
                    use_ssl=self.use_ssl,
                    keyfile_path=self.keyfile_path,
                    keyfile_password=self.keyfile_password,
                    certfile_path=self.certfile_path,
                ) as zk:
                    response = zk.srvr
                    if response:
                        any_host = host
                        break
            except KazooTimeoutError:  # in the case of having a dead unit in relation data
                logger.debug(f"TIMEOUT - {host}")
                continue

        return any_host or ""

    @property
    def server_members(self) -> Set[str]:
        """The current members within the ZooKeeper quorum.

        Returns:
            A set of ZK member strings
                e.g {"server.1=10.141.78.207:2888:3888:participant;0.0.0.0:2181"}
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            members, _ = zk.config

        return set(members)

    @property
    def config_version(self) -> int:
        """The current config version for ZooKeeper.

        Returns:
            The zookeeper config version decoded from base16
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            _, version = zk.config

        return version

    @property
    def members_syncing(self) -> bool:
        """Flag to check if any quorum members are currently syncing data.

        Returns:
            True if any members are syncing. Otherwise False.
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            result = zk.mntr

        try:
            zk_pending_syncs = result["zk_pending_syncs"]
        except KeyError:  # missing key, no quorum, no syncing
            return False

        if (
            result.get("zk_peer_state", "") == "leading - broadcast"
            and float(zk_pending_syncs) == 0
        ):
            return False

        return True

    @property
    def members_broadcasting(self) -> bool:
        """Flag to check if any quorum members are currently broadcasting.

        Returns:
            True if any members are currently broadcasting. Otherwise False.
        """
        for host in self.hosts:
            try:
                with ZooKeeperClient(
                    host=host,
                    client_port=self.client_port,
                    username=self.username,
                    password=self.password,
                    use_ssl=self.use_ssl,
                    keyfile_path=self.keyfile_path,
                    keyfile_password=self.keyfile_password,
                    certfile_path=self.certfile_path,
                ) as zk:
                    if not zk.is_ready:
                        return False
            except KazooTimeoutError:  # in the case of having a dead unit in relation data
                logger.debug(f"TIMEOUT - {host}")
                return False

        return True

    def add_members(self, members: Iterable[str]) -> None:
        """Adds new members to the members' dynamic config.

        Raises:
            MembersSyncingError: if any members are busy syncing data
            MemberNotReadyError: if any members are not yet broadcasting
        """
        if self.members_syncing:
            raise MembersSyncingError("Unable to add members - some members are syncing")

        for member in members:
            host = member.split("=")[1].split(":")[0]

            try:
                # individual connections to each server
                with ZooKeeperClient(
                    host=host,
                    client_port=self.client_port,
                    username=self.username,
                    password=self.password,
                    use_ssl=self.use_ssl,
                    keyfile_path=self.keyfile_path,
                    keyfile_password=self.keyfile_password,
                    certfile_path=self.certfile_path,
                ) as zk:
                    if not zk.is_ready:
                        raise MemberNotReadyError(f"Server is not ready: {host}")
            except KazooTimeoutError as e:  # for when units are departing
                logger.debug(str(e))
                continue

            # specific connection to leader
            with ZooKeeperClient(
                host=self.zk_host,
                client_port=self.client_port,
                username=self.username,
                password=self.password,
                use_ssl=self.use_ssl,
                keyfile_path=self.keyfile_path,
                keyfile_password=self.keyfile_password,
                certfile_path=self.certfile_path,
            ) as zk:
                zk.client.reconfig(
                    joining=member, leaving=None, new_members=None, from_config=self.config_version
                )

    def remove_members(self, members: Iterable[str]) -> None:
        """Removes members from the members' dynamic config.

        Raises:
            MembersSyncingError: if any members are busy syncing data
        """
        if self.members_syncing:
            raise MembersSyncingError("Unable to remove members - some members are syncing")

        for member in members:
            member_id = re.findall(r"server.([0-9]+)", member)[0]
            with ZooKeeperClient(
                host=self.zk_host,
                client_port=self.client_port,
                username=self.username,
                password=self.password,
                use_ssl=self.use_ssl,
                keyfile_path=self.keyfile_path,
                keyfile_password=self.keyfile_password,
                certfile_path=self.certfile_path,
            ) as zk:
                zk.client.reconfig(
                    joining=None,
                    leaving=member_id,
                    new_members=None,
                    from_config=self.config_version,
                )

    def leader_znodes(self, path: str) -> Set[str]:
        """Grabs all children zNodes for a path on the current quorum leader.

        Args:
            path: the 'root' path to search from

        Returns:
            Set of all nested child zNodes
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            all_znode_children = zk.get_all_znode_children(path=path)

        return all_znode_children

    def create_znode_leader(self, path: str, acls: List[ACL] | None = None) -> None:
        """Creates a new zNode on the current quorum leader with given ACLs.

        Args:
            path: the zNode path to set
            acls: the ACLs to be set on that path
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            zk.create_znode(path=path, acls=acls)

    def set_acls_znode_leader(self, path: str, acls: List[ACL] | None = None) -> None:
        """Updates ACLs for an existing zNode on the current quorum leader.

        Args:
            path: the zNode path to update
            acls: the new ACLs to be set on that path
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            zk.set_acls(path=path, acls=acls)

    def delete_znode_leader(self, path: str) -> None:
        """Deletes a zNode path from the current quorum leader.

        Args:
            path: the zNode path to delete
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            zk.delete_znode(path=path)

    def get_version(self) -> str:
        """Get ZooKeeper service version from srvr 4lw.

        Returns:
            String of ZooKeeper service version
        """
        with ZooKeeperClient(
            host=self.zk_host,
            client_port=self.client_port,
            username=self.username,
            password=self.password,
            use_ssl=self.use_ssl,
            keyfile_path=self.keyfile_path,
            keyfile_password=self.keyfile_password,
            certfile_path=self.certfile_path,
        ) as zk:
            return zk.srvr["Zookeeper version"].split("-", maxsplit=1)[0]


class ZooKeeperClient:
    """Handler for ZooKeeper connections and running 4lw client commands."""

    def __init__(
        self,
        host: str,
        client_port: int,
        username: str,
        password: str,
        use_ssl: bool = False,
        keyfile_path: Optional[str] = None,
        keyfile_password: Optional[str] = None,
        certfile_path: Optional[str] = None,
    ):
        self.host = host
        self.client_port = client_port
        self.username = username
        self.password = password
        self.client = KazooClient(
            hosts=f"{host}:{client_port}",
            timeout=1.0,
            sasl_options={"mechanism": "DIGEST-MD5", "username": username, "password": password},
            keyfile=keyfile_path,
            keyfile_password=keyfile_password,
            certfile=certfile_path,
            verify_certs=False,
            use_ssl=use_ssl,
        )
        self.client.start()

    def __enter__(self):
        return self

    def __exit__(self, object_type, value, traceback):
        self.client.stop()

    def _run_4lw_command(self, command: str):
        return self.client.command(command.encode())

    @property
    def config(self) -> Tuple[List[str], int]:
        """Retrieves the dynamic config for a ZooKeeper service.

        Returns:
            Tuple of the decoded config list, and decoded config version
        """
        response = self.client.get("/zookeeper/config")
        if response:
            result = str(response[0].decode("utf-8")).splitlines()
            version = int(result.pop(-1).split("=")[1], base=16)
        else:
            raise

        return result, version

    @property
    def srvr(self) -> Dict[str, Any]:
        """Retrieves attributes returned from the 'srvr' 4lw command.

        Returns:
            Mapping of field and setting returned from `srvr`
        """
        response = self._run_4lw_command("srvr")

        result = {}
        for item in response.splitlines():
            k = re.split(": ", item)[0]
            v = re.split(": ", item)[1]
            result[k] = v

        return result

    @property
    def mntr(self) -> Dict[str, Any]:
        """Retrieves attributes returned from the 'mntr' 4lw command.

        Returns:
            Mapping of field and setting returned from `mntr`
        """
        response = self._run_4lw_command("mntr")

        result = {}
        for item in response.splitlines():
            if re.search("=|\\t", item):
                k = re.split("=|\\t", item)[0]
                v = re.split("=|\\t", item)[1]
                result[k] = v
            else:
                result[item] = ""

        return result

    @property
    def is_ready(self) -> bool:
        """Flag to confirm connected ZooKeeper server is connected and broadcasting.

        Returns:
            True if server is broadcasting. Otherwise False.
        """
        if self.client.connected:
            return "broadcast" in self.mntr.get("zk_peer_state", "")
        return False

    def get_all_znode_children(self, path: str) -> Set[str]:
        """Recursively gets all children for a given parent znode path.

        Args:
            path: the desired parent znode path to recurse

        Returns:
            Set of all nested children znode paths for the given parent
        """
        children = self.client.get_children(path) or []

        result = set()
        for child in children:
            if path + child != "/zookeeper":
                result.update(self.get_all_znode_children(path.rstrip("/") + "/" + child))
        if path != "/":
            result.add(path)

        return result

    def delete_znode(self, path: str) -> None:
        """Drop znode and all it's children from ZK tree.

        Args:
            path: the desired znode path to delete
        """
        if not self.client.exists(path):
            return
        self.client.delete(path, recursive=True)

    def create_znode(self, path: str, acls: List[ACL] | None = None) -> None:
        """Create new znode.

        Args:
            path: the desired znode path to create
            acls: the acls for the new znode
        """
        self.client.create(path, acl=acls, makepath=True)

    def get_acls(self, path: str) -> List[ACL]:
        """Gets acls for a desired znode path.

        Args:
            path: the desired znode path

        Returns:
            List of the acls set for the given znode
        """
        acl_list = self.client.get_acls(path)

        return acl_list if acl_list else []

    def set_acls(self, path: str, acls: List[ACL] | None = None) -> None:
        """Sets acls for a desired znode path.

        Args:
            path: the desired znode path
            acls: the acls to set to the given znode
        """
        self.client.set_acls(path, acls)
