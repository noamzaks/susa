from __future__ import annotations

from dataclasses import dataclass

from susa.communicators.shell import ShellCommunicator
from susa.core.stream import InputOutputStream


# Input sent before a login program prompts is usually discarded.
@dataclass(frozen=True)
class Login:
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
