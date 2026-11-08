from __future__ import annotations

import contextlib
import shlex
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from typing_extensions import override

from susa.communicators.container import ContainerCommunicator
from susa.core.communicator import HOST
from susa.core.resource import Resource
from susa.libvirt._virsh import LVURI
from susa.utilities.generic import guarded, random_id, wait_until
from susa.utilities.networking import SubnetReservation


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
        remove = ["podman", "rm", "--force", "--time=0", "--ignore", self.name]
        directory = shlex.quote(str(self.directory))
        command = f"{shlex.join(remove)} > /dev/null; rm -r {directory}"
        try:
            with guarded(command) as self.guard:
                self._start(self.directory)
        except BaseException:
            self.directory = None
            raise

    @override
    def destroy(self) -> None:
        assert self.directory is not None
        self.defaults.close()
        self.guard.release()
        self.directory = None

    def options(self) -> list[str]:
        assert self.directory is not None
        devices = ["/dev/net/tun", *(["/dev/kvm"] if Path("/dev/kvm").exists() else [])]
        return [
            f"--name={self.name}",
            "--cap-add=NET_ADMIN,NET_RAW",
            "--security-opt=unmask=/proc/sys",
            "--security-opt=label=disable",
            *(f"--device={device}" for device in devices),
            f"--volume={self.directory}/libvirt:/run/libvirt",
            *(f"--volume={mount}:{mount}" for mount in self.mounts),
        ]

    def pid(self) -> int:
        return int(
            self.podman("inspect", "--format", "{{.State.Pid}}", self.name).stdout
        )

    def podman(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["podman", *args], check=check, capture_output=True, text=True
        )

    def _start(self, directory: Path) -> None:
        socket = directory / "libvirt/virtqemud-sock"
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
        wait_until(socket.exists, self.start_timeout)
        self.podman(
            "exec", self.name, "systemctl", "is-system-running", "--wait", check=False
        )
        pid = self.pid()
        uri = f"qemu+unix:///system?socket={socket}"
        lock = directory / "subnets.lock"
        self.defaults.enter_context(HOST.set(ContainerCommunicator(pid)))
        self.defaults.enter_context(LVURI.set(uri))
        self.defaults.enter_context(SubnetReservation.LOCK.set(str(lock)))
