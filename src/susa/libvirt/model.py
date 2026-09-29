from __future__ import annotations

import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar, cast

import pydantic
import pydantic_xml
from pydantic_core import core_schema
from typing_extensions import Self

from susa.utilities.builder import builder_calls
from susa.utilities.schema import instance_schema

T = TypeVar("T", bound=pydantic_xml.BaseXmlModel)


class Model(ABC, Generic[T]):
    xml_model: T
    xml_model_type: ClassVar[type[pydantic_xml.BaseXmlModel]]

    @abstractmethod
    def __init__(self, xml_model: T | None = None) -> None: ...

    def tree(self) -> ET.Element:
        return self.xml_model.to_xml_tree(exclude_none=True)

    def build(self) -> str:
        tree = self.tree()
        ET.indent(tree)
        return ET.tostring(tree, encoding="unicode")

    @classmethod
    def parse(cls, xml: str | bytes) -> Self:
        return cls(xml_model=cast(T, cls.xml_model_type.from_xml(xml)))

    # Models are pydantic types, validated from builder calls (see `builder_calls`) or XML, and serialized to XML.
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        schema = core_schema.tagged_union_schema(
            {
                "calls": handler.generate_schema(builder_calls(cls)),
                "xml": core_schema.no_info_after_validator_function(
                    cls.parse, core_schema.str_schema()
                ),
            },
            lambda value: "xml" if isinstance(value, (str, bytes)) else "calls",
        )
        return instance_schema(cls, schema, lambda model: model.build())
