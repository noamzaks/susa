from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class Resource(ABC):
    @abstractmethod
    def create(self) -> None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    def __enter__(self) -> Self:
        self.create()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.destroy()
