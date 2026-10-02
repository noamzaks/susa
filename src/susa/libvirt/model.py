from __future__ import annotations

import xml.etree.ElementTree as ET
from abc import abstractmethod
from typing import ClassVar, Generic, TypeVar, cast

import pydantic
import pydantic_xml
from pydantic_core import core_schema
from typing_extensions import Self, override

from susa.utilities.recipe import recipe_schema
from susa.utilities.serializable import Serializable

T = TypeVar("T", bound=pydantic_xml.BaseXmlModel)


class Model(Serializable, Generic[T]):
    xml_model: T
    xml_model_type: ClassVar[type[pydantic_xml.BaseXmlModel]]

    @abstractmethod
    def __init__(self, xml_model: T | None = None) -> None: ...

    def build(self) -> str:
        tree = self.xml_model.to_xml_tree(exclude_none=True)
        ET.indent(tree)
        return ET.tostring(tree, encoding="unicode")

    @classmethod
    def parse(cls, xml: str | bytes) -> Self:
        return cls(xml_model=cast(T, cls.xml_model_type.from_xml(xml)))

    # A recipe (see `recipe_schema`) or XML.
    @classmethod
    @override
    def serialized_schema(
        cls, handler: pydantic.GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.tagged_union_schema(
            {
                "recipe": recipe_schema(cls),
                "xml": core_schema.no_info_after_validator_function(
                    cls.parse, core_schema.str_schema()
                ),
            },
            lambda value: "xml" if isinstance(value, str) else "recipe",
        )

    @override
    def serialize(self) -> str:
        return self.build()
