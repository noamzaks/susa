from __future__ import annotations

import shlex
from collections.abc import Sequence

from typing_extensions import override

from susa.core.communicator import AsyncCommand, HostAsyncCommandRunner
from susa.core.serializable import JSON


class ContainerCommunicator(HostAsyncCommandRunner):
    def __init__(
        self, pid: int, namespaces: Sequence[str] = ("user", "net", "pid")
    ) -> None:
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

    @override
    def __getstate__(self) -> JSON:
        return {"pid": self.pid, "namespaces": list[JSON](self.namespaces)}

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, dict)
        pid, namespaces = state["pid"], state["namespaces"]
        assert isinstance(pid, int) and isinstance(namespaces, list)
        self.pid = pid
        self.namespaces = [str(namespace) for namespace in namespaces]
