from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from typing_extensions import override

from susa.core.resource import Resource
from susa.utilities.generic import random_id, wait_until
from susa.utilities.namespaces import join_namespaces
from susa.utilities.networking import SubnetReservation


# libvirt in a rootless container, whose user and network namespaces this process joins (for good) when it's created,
# so that what it runs (e.g. ssh) reaches the machines. Until it's destroyed, connections (and subnet reservations)
# default to it, and podman keeps working through a service of its own.
class LibvirtContainer(Resource):
    IMAGE = "localhost/susa-libvirt"
    CONTEXT = Path(__file__).parent / "image"
    START_TIMEOUT = 60

    def __init__(self, mounts: Sequence[str] = ()) -> None:
        self.mounts = list(mounts)
        self.name = f"susa-{random_id(10)}"
        self.directory: Path | None = None
        self.service: subprocess.Popen[bytes] | None = None
        self.saved: dict[str, str | None] = {}

    @override
    def create(self) -> None:
        assert self.directory is None
        directory = self.directory = Path(tempfile.mkdtemp(prefix="susa-"))
        (directory / "libvirt").mkdir()
        if subprocess.run(
            ["podman", "image", "exists", self.IMAGE], check=False
        ).returncode:
            subprocess.run(
                ["podman", "build", "-t", self.IMAGE, self.CONTEXT], check=True
            )
        environment = self.environment()
        service = [
            "podman",
            "system",
            "service",
            "--time=0",
            environment["CONTAINER_HOST"],
        ]
        self.service = subprocess.Popen(service)
        self.podman("run", "--detach", "--rm", *self.options(), self.IMAGE)
        # Systemd creates the socket, and then the rest of booting can be waited for. It exits with an error when
        # booting finished with a failed unit ("degraded") too.
        wait_until((directory / "libvirt/virtqemud-sock").exists, self.START_TIMEOUT)
        self.podman(
            "exec", self.name, "systemctl", "is-system-running", "--wait", check=False
        )
        wait_until((directory / "podman.sock").exists, self.START_TIMEOUT)
        pid = self.podman("inspect", "--format", "{{.State.Pid}}", self.name)
        join_namespaces(int(pid), "user", "net")
        self.saved = {name: os.environ.get(name) for name in environment}
        os.environ.update(environment)

    @override
    def destroy(self) -> None:
        assert self.directory is not None and self.service is not None
        self.podman("rm", "--force", "--time=0", self.name)
        self.service.terminate()
        self.service.wait()
        for name, value in self.saved.items():
            if value is None:
                del os.environ[name]
            else:
                os.environ[name] = value
        shutil.rmtree(self.directory)
        self.directory, self.service, self.saved = None, None, {}

    def environment(self) -> dict[str, str]:
        assert self.directory is not None
        socket = self.directory / "libvirt/virtqemud-sock"
        return {
            "CONTAINER_HOST": f"unix://{self.directory}/podman.sock",
            "LIBVIRT_DEFAULT_URI": f"qemu+unix:///system?socket={socket}",
            SubnetReservation.LOCK_VARIABLE: str(self.directory / "subnets.lock"),
        }

    def options(self) -> list[str]:
        assert self.directory is not None
        devices = ["/dev/net/tun", *(["/dev/kvm"] if Path("/dev/kvm").exists() else [])]
        return [
            f"--name={self.name}",
            "--cap-add=NET_ADMIN,NET_RAW",
            # libvirt sets up its bridges' sysctls (only the container's network's).
            "--security-opt=unmask=/proc/sys",
            # Lets QEMU use the mounts as they are.
            "--security-opt=label=disable",
            *(f"--device={device}" for device in devices),
            f"--volume={self.directory}/libvirt:/run/libvirt",
            *(f"--volume={mount}:{mount}" for mount in self.mounts),
        ]

    def podman(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["podman", *args], check=check, capture_output=True, text=True
        )
        return result.stdout.strip()
