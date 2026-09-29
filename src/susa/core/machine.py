from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from io import BytesIO
from typing import TYPE_CHECKING

from susa.core.interface import Interface
from susa.core.resource import Resource
from susa.core.stream import InputOutputStream

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
        assert len(ips) != 0
        return ips[0]


class Snapshot(Resource):
    @abstractmethod
    def revert(self) -> None: ...


class Snapshottable(ABC):
    @abstractmethod
    def snapshot(self) -> Snapshot: ...


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
