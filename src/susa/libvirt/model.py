from __future__ import annotations

import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar, cast

import pydantic_xml
from typing_extensions import Self

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
