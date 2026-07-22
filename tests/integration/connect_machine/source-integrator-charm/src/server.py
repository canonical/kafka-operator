import logging
import os
import subprocess

from kafkacl import BasePluginServer

logger = logging.getLogger(__name__)


class SimplePluginServer(BasePluginServer):
    """A simple HTTP plugin server for test purposes.

    WARNING: this is in no way meant to be used in production code.
    """

    plugin_url: str

    def __init__(
        self,
        base_address: str,
        port: int,
        resource_path: str,
        logs_path: str = "/var/log/plugin-server.log",
    ):
        self.port = port
        self.resource_path = resource_path
        self.logs_path = logs_path
        self.plugin_url = f"http://{base_address}:{self.port}/plugin.tar"
        self.pid_file = "/var/run/plugin-server.pid"

    def start(self):
        cmd = f"nohup python3 -m http.server {self.port}"
        process = subprocess.Popen(
            cmd.split(),
            stdout=open("/dev/null", "w"),
            stderr=open(self.logs_path, "a+"),
            preexec_fn=os.setpgrp,
            cwd=self.resource_path,
        )
        logger.info(process.pid)
        open(self.pid_file, "w").write(f"{process.pid}\n")

    def stop(self):
        pid = open(self.pid_file).read().strip()
        os.system(f"kill {pid}")
        os.remove(self.pid_file)
        return

    def configure(self):
        return

    def health_check(self):
        return os.path.exists(self.pid_file)
