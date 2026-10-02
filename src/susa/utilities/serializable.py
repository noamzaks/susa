from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

import pydantic
from pydantic_core import core_schema
from typing_extensions import override

S = TypeVar("S", bound="Serializable")


# A pydantic type that's validated from its serialized form (see `serialized_schema`) and serialized back to it, which
# pickling goes through as well.
class Serializable(ABC):
    @classmethod
    @abstractmethod
    def serialized_schema(
        cls, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema: ...

    @abstractmethod
    def serialize(self) -> Any: ...

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        schema = cls.serialized_schema(handler)
        return core_schema.no_info_wrap_validator_function(
            lambda value, validate: (
                value if isinstance(value, cls) else validate(value)
            ),
            schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value.serialize(), return_schema=schema
            ),
        )

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        return deserialize, (type(self), self.serialize())


def deserialize(cls: type[S], data: Any) -> S:
    return pydantic.TypeAdapter(cls).validate_python(data)
