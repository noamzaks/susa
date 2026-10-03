from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from io import BytesIO
from typing import TYPE_CHECKING

from typing_extensions import override

from susa.core.interface import Interface
from susa.core.resource import Resource
from susa.core.stream import InputOutputStream, SavedOutputStream
from susa.utilities.generic import Deadline
from susa.utilities.networking import wait_until_ping

if TYPE_CHECKING:
    from PIL.ImageFile import ImageFile


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
        assert ips
        return ips[0]


class Snapshot(Resource):
    @abstractmethod
    def revert(self) -> None: ...


class Snapshottable(ABC):
    @abstractmethod
    def snapshot(self) -> Snapshot: ...


class SnapshotGroup(Snapshot):
    def __init__(self, snapshots: Sequence[Snapshot]) -> None:
        self.snapshots = snapshots

    @override
    def create(self) -> None:
        for snapshot in self.snapshots:
            snapshot.create()

    @override
    def destroy(self) -> None:
        for snapshot in reversed(self.snapshots):
            snapshot.destroy()

    @override
    def revert(self) -> None:
        for snapshot in self.snapshots:
            snapshot.revert()


class SnapshottableGroup(Snapshottable):
    def __init__(self, snapshottables: Sequence[Snapshottable]) -> None:
        self.snapshottables = snapshottables

    @override
    def snapshot(self) -> SnapshotGroup:
        return SnapshotGroup([s.snapshot() for s in self.snapshottables])


class Powerable(ABC):
    @property
    @abstractmethod
    def is_powered_on(self) -> bool: ...

    @abstractmethod
    def power_on(self) -> None: ...

    @abstractmethod
    def power_off(self) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...

    @abstractmethod
    def reboot(self) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...


@dataclass(frozen=True)
class Screenshot:
    data: bytes
    mime_type: str | None = None

    @cached_property
    def image(self) -> ImageFile:
        from PIL import Image

        return Image.open(BytesIO(self.data))

    @cached_property
    def text(self) -> str:
        from pytesseract.pytesseract import image_to_string

        text: str = image_to_string(self.image)
        return text


class Screenshottable(ABC):
    @abstractmethod
    def screenshot(self) -> Screenshot: ...


class Serial(Resource, InputOutputStream): ...


class SerialAccessible(ABC):
    @abstractmethod
    def serial(self) -> Serial: ...


# Booting is over once it answers ping and its serial console is quiet for `quiet_time`. If it isn't by `timeout`, the
# error has what its console said meanwhile.
def wait_until_booted(
    machine: Machine, timeout: float | None = None, quiet_time: float = 5
) -> None:
    assert isinstance(machine, SerialAccessible)
    with machine.serial() as serial:
        console = SavedOutputStream(serial)
        deadline = Deadline(timeout)
        try:
            wait_until_ping(machine.ip, deadline.remaining())
            console.wait_until_quiet(quiet_time, deadline.remaining())
        except (TimeoutError, EOFError) as e:
            with contextlib.suppress(EOFError):
                console.read()
            output = console.data.decode(errors="backslashreplace")
            raise TimeoutError(f"{machine.name} didn't boot: {e}\n{output}") from e
