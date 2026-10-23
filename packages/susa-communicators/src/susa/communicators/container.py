from __future__ import annotations

import shlex
from collections.abc import Sequence

from typing_extensions import override

from susa.core.communicator import AsyncCommand, HostAsyncCommandRunner


# Runs commands in a process' namespaces (e.g. a container's user and network ones), with this system's programs and
# files. Unlike with `podman exec`, they're this process' children, which stop when they're killed.
class ContainerCommunicator(HostAsyncCommandRunner):
    def __init__(self, pid: int, namespaces: Sequence[str] = ("user", "net")) -> None:
        self.pid = pid
        self.namespaces = list(namespaces)

    @override
    def start(self, command: str) -> AsyncCommand:
        namespaces = [f"--{namespace}" for namespace in self.namespaces]
        nsenter = [
            "nsenter",
            f"--target={self.pid}",
            *namespaces,
            "--preserve-credentials",
        ]
        return super().start(shlex.join([*nsenter, "sh", "-c", command]))
