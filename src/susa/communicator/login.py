from __future__ import annotations

from dataclasses import dataclass

from susa.core.stream import InputOutputStream

ENTER = b"\r"
QUIET_TIMEOUT = 60


# A prelude (see `ShellCommunicator`) that logs in: the username (if any), then the password, each once the terminal is
# quiet (since input sent before a login program prompts is usually discarded).
@dataclass(frozen=True)
class Login:
    password: str
    username: str | None = None
    quiet_time: float = 3

    def __call__(self, stream: InputOutputStream) -> None:
        for line in [self.username, self.password]:
            if line is None:
                continue
            stream.wait_until_quiet(self.quiet_time, QUIET_TIMEOUT)
            stream.write(line.encode() + ENTER)
