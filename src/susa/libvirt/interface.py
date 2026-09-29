from __future__ import annotations

from typing_extensions import override

from susa.core.interface import Interface


# TODO: move this to core with some appropriate name, then just make class LVInterface(BasicInterface): pass or something like that.
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
