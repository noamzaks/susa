from __future__ import annotations

from abc import ABC, abstractmethod


class Interface(ABC):
    @property
    @abstractmethod
    def mac(self) -> str: ...

    @property
    @abstractmethod
    def ip(self) -> str | None: ...
