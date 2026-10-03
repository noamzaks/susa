from __future__ import annotations

import typing
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import pydantic_xml
from typing_extensions import Self, override

T = TypeVar("T", bound=pydantic_xml.BaseXmlModel)


class Model(ABC, Generic[T]):
    xml_model: T

    @abstractmethod
    def __init__(self, xml_model: T | None = None) -> None: ...

    def build(self) -> str:
        tree = self.xml_model.to_xml_tree(exclude_none=True)
        ET.indent(tree)
        return ET.tostring(tree, encoding="unicode")

    @classmethod
    def parse(cls, xml: str | bytes) -> Self:
        return cls(xml_model=cls.xml_model_type().from_xml(xml))

    # The `T` it's a `Model` of.
    @classmethod
    def xml_model_type(cls) -> type[T]:
        [base] = cls.__orig_bases__  # type: ignore
        [xml_model_type] = typing.get_args(base)
        return typing.cast("type[T]", xml_model_type)

    # Models are values.
    @override
    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and other.build() == self.build()
