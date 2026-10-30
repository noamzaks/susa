from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable, Generator
from typing import Any, Generic, TypeVar, overload

T = TypeVar("T")


class Variable(Generic[T]):
    @overload
    def __init__(self, default: T) -> None: ...

    @overload
    def __init__(self, *, default_factory: Callable[[], T]) -> None: ...

    # The default factory is called once, when the default is first needed.
    def __init__(
        self, default: Any = None, *, default_factory: Callable[[], T] | None = None
    ) -> None:
        self._default = functools.cache(default_factory or (lambda: default))
        self._values: list[T] = []

    def get(self) -> T:
        return self._values[-1] if self._values else self._default()

    @contextlib.contextmanager
    def set(self, value: T) -> Generator[None, None, None]:
        self._values.append(value)
        try:
            yield
        finally:
            self._values.pop()
