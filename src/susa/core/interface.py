from __future__ import annotations

from abc import ABC, abstractmethod

from typing_extensions import override


class Interface(ABC):
    @property
    @abstractmethod
    def mac(self) -> str: ...

    @property
    @abstractmethod
    def ip(self) -> str | None: ...


class BasicInterface(Interface):
    def __init__(self, mac: str, ip: str | None = None) -> None:
        self._mac = mac
        self._ip = ip

    @property
    @override
    def mac(self) -> str:
        return self._mac

    @property
    @override
    def ip(self) -> str | None:
        return self._ip
