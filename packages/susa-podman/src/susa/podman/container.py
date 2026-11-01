from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator, Mapping, Sequence
from pathlib import Path

from typing_extensions import override

from susa.communicators.container import ContainerCommunicator
from susa.core.communicator import HOST
from susa.core.resource import Resource
from susa.libvirt._virsh import URI
from susa.utilities.generic import random_id, wait_until
from susa.utilities.networking import SubnetReservation


# libvirt in a rootless container (of the image, built if it's missing). Until it's destroyed, virsh defaults to it,
# and commands that run on the host (e.g. ssh's) run in its network, where they reach its machines. So do those of
# processes started meanwhile, through the environment.
class LibvirtContainer(Resource):
    CONTEXT = Path(__file__).parent / "image"

    def __init__(
        self,
        mounts: Sequence[str] = (),
        image: str = "susa-libvirt",
        start_timeout: float = 60,
    ) -> None:
        self.mounts = list(mounts)
        self.image = image
        self.start_timeout = start_timeout
        self.name = f"susa-{random_id(10)}"
        self.directory: Path | None = None
        self.defaults = contextlib.ExitStack()

    @override
    def create(self) -> None:
        assert self.directory is None
        self.directory = Path(tempfile.mkdtemp(prefix="susa-"))
        socket = self.directory / "libvirt/virtqemud-sock"
        socket.parent.mkdir()
        if self.podman("image", "exists", self.image, check=False).returncode:
            build = [
                "podman",
                "build",
                "--tag",
                self.image,
                str(LibvirtContainer.CONTEXT),
            ]
            subprocess.run(build, check=True)
        self.podman("run", "--detach", "--rm", *self.options(), self.image)
        # Systemd creates the socket, and then the rest of booting can be waited for. It exits with an error when
        # booting finished with a failed unit ("degraded") too.
        wait_until(socket.exists, self.start_timeout)
        self.podman(
            "exec", self.name, "systemctl", "is-system-running", "--wait", check=False
        )
        pid = self.pid()
        uri = f"qemu+unix:///system?socket={socket}"
        lock = self.directory / "subnets.lock"
        self.defaults.enter_context(HOST.set(ContainerCommunicator(pid)))
        self.defaults.enter_context(URI.set(uri))
        self.defaults.enter_context(SubnetReservation.LOCK.set(lock))
        cls = ContainerCommunicator
        host = {f"{cls.__module__}.{cls.__qualname__}": {"pid": pid}}
        environment = {
            "SUSA_SESSION": json.dumps({"objects": [{"host": host}]}),
            "LIBVIRT_DEFAULT_URI": uri,
            "SUSA_SUBNETS_LOCK": str(lock),
        }
        self.defaults.enter_context(self.environment(environment))

    @override
    def destroy(self) -> None:
        assert self.directory is not None
        self.defaults.close()
        self.podman("rm", "--force", "--time=0", self.name)
        shutil.rmtree(self.directory)
        self.directory = None

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

    def pid(self) -> int:
        return int(
            self.podman("inspect", "--format", "{{.State.Pid}}", self.name).stdout
        )

    @staticmethod
    @contextlib.contextmanager
    def environment(variables: Mapping[str, str]) -> Generator[None, None, None]:
        previous = {name: os.environ.get(name) for name in variables}
        os.environ.update(variables)
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    del os.environ[name]
                else:
                    os.environ[name] = value

    def podman(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["podman", *args], check=check, capture_output=True, text=True
        )
