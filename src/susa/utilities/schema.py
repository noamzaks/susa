from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_core import core_schema


# A pydantic schema that takes instances of `cls` as they are and anything else through `schema`, and serializes
# them with `serialize` (into `return_schema`).
def instance_schema(
    cls: type[Any],
    schema: core_schema.CoreSchema,
    serialize: Callable[[Any], Any],
    return_schema: core_schema.CoreSchema | None = None,
) -> core_schema.CoreSchema:
    def validate(value: Any, handler: core_schema.ValidatorFunctionWrapHandler) -> Any:
        return value if isinstance(value, cls) else handler(value)

    validate.__name__ = cls.__name__
    return core_schema.no_info_wrap_validator_function(
        validate,
        schema,
        serialization=core_schema.plain_serializer_function_ser_schema(
            serialize, return_schema=return_schema
        ),
    )
