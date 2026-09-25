from abc import ABC, abstractmethod
from dataclasses import dataclass

from susa.core.interface import Interface
from susa.core.resource import Resource
from susa.core.stream import Stream


class Snapshot(Resource):
    """A snapshot of a `Machine`. Destroying it reverts the machine to it."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def revert(self) -> None: ...


class Snapshottable(ABC):
    @abstractmethod
    def snapshot(self) -> Snapshot:
        """Take a snapshot of the machine as it is now."""


class Powerable(ABC):
    @property
    @abstractmethod
    def is_powered_on(self) -> bool: ...

    @abstractmethod
    def power_on(self) -> None: ...

    @abstractmethod
    def power_off(self) -> None:
        """Turn the machine off immediately, like pulling the plug."""

    @abstractmethod
    def shutdown(self) -> None:
        """Ask the machine's OS to shut down. Returns without waiting for it to do so."""

    @abstractmethod
    def reboot(self) -> None:
        """Ask the machine's OS to reboot. Returns without waiting for it to do so."""

    @abstractmethod
    def reset(self) -> None:
        """Restart the machine immediately, like pressing its reset button."""


@dataclass(frozen=True)
class Screenshot:
    data: bytes
    mime_type: str | None = None


class Screenshottable(ABC):
    @abstractmethod
    def screenshot(self) -> Screenshot: ...


class Serial(Resource):
    """A connection to a machine's serial console. Output from before it's created is not available."""

    @property
    @abstractmethod
    def output(self) -> Stream: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...


class SerialAccessible(ABC):
    """Something with a serial console."""

    @abstractmethod
    def serial(self) -> Serial:
        """A new, already created, connection to the serial console. Destroy it when done (or use it in a `with`
        block)."""


class Machine(Resource):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def interfaces(self) -> list[Interface]: ...

    @property
    def ips(self) -> list[str]:
        return [
            interface.ip for interface in self.interfaces if interface.ip is not None
        ]

    @property
    def ip(self) -> str:
        ips = self.ips
        assert len(ips) != 0
        return ips[0]
