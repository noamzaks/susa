from __future__ import annotations

import contextlib
import functools
import json
import os
from collections.abc import Callable, Generator
from typing import Any, Generic, TypeVar, cast, overload

from typing_extensions import override

from susa.core.serializable import JSON, Serializable, deserialize, serialize

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


# Kept in an environment variable too while it's set, so processes started meanwhile start with its value. Its values
# are strings, `None` or serializable (as JSON).
class EnvironmentVariable(Variable[T]):
    @overload
    def __init__(self, name: str, default: T) -> None: ...

    @overload
    def __init__(self, name: str, *, default_factory: Callable[[], T]) -> None: ...

    def __init__(
        self,
        name: str,
        default: Any = None,
        *,
        default_factory: Callable[[], T] | None = None,
    ) -> None:
        self.name = name
        factory = default_factory or (lambda: default)
        super().__init__(default_factory=lambda: self._initial(factory))

    @override
    @contextlib.contextmanager
    def set(self, value: T) -> Generator[None, None, None]:
        previous = os.environ.get(self.name)
        os.environ[self.name] = json.dumps(self._encode(value))
        try:
            with super().set(value):
                yield
        finally:
            if previous is None:
                del os.environ[self.name]
            else:
                os.environ[self.name] = previous

    def _initial(self, default: Callable[[], T]) -> T:
        text = os.environ.get(self.name)
        if text is None:
            return default()
        value: JSON = json.loads(text)
        return cast("T", deserialize(value) if isinstance(value, dict) else value)

    @staticmethod
    def _encode(value: object) -> JSON:
        if isinstance(value, Serializable):
            return serialize(value)
        assert value is None or isinstance(value, str)
        return value
