from typing_extensions import override

from susa.core.interface import Interface


class LVInterface(Interface):
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
