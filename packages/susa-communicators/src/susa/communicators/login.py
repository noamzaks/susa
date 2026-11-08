from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from susa.communicators.shell import ShellCommunicator
from susa.core.serializable import JSON, Serializable
from susa.core.stream import InputOutputStream


@dataclass
class Login(Serializable):
    QUIET_TIMEOUT = 60

    password: str
    username: str | None = None
    quiet_time: float = 3

    def __call__(self, stream: InputOutputStream) -> None:
        for line in [self.username, self.password]:
            if line is None:
                continue
            stream.wait_until_quiet(self.quiet_time, Login.QUIET_TIMEOUT)
            stream.write(line.encode() + ShellCommunicator.ENTER)

    @override
    def __getstate__(self) -> JSON:
        return {
            "password": self.password,
            "username": self.username,
            "quiet_time": self.quiet_time,
        }

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, dict)
        password, username, quiet_time = (
            state["password"],
            state["username"],
            state["quiet_time"],
        )
        assert isinstance(password, str) and isinstance(quiet_time, (int, float))
        assert username is None or isinstance(username, str)
        Login.__init__(self, password, username, quiet_time)
