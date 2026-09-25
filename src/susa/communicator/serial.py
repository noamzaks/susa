from typing_extensions import override

from susa.communicator.shell import Child, Prelude, QuietSpawn, ShellCommunicator
from susa.core.machine import Serial


class SerialSpawn(QuietSpawn):
    def __init__(self, serial: Serial, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.serial = serial

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        if timeout is None or timeout == -1:
            timeout = self.timeout or 0
        return self.serial.output.read(size, timeout)

    def send(self, s: bytes) -> int:
        self.serial.write(s)
        return len(s)

    def sendline(self, s: bytes = b"") -> int:
        return self.send(s + b"\r")

    def sendintr(self) -> None:
        self.send(b"\x03")

    def close(self) -> None:
        self.serial.destroy()


class SerialCommunicator(ShellCommunicator):
    """A shell over `serial`, which it takes ownership of."""

    def __init__(self, serial: Serial, prelude: Prelude | None = None) -> None:
        super().__init__(prelude)
        self.serial = serial

    @override
    def spawn(self) -> Child:
        return SerialSpawn(self.serial)
