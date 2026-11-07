from __future__ import annotations

import bisect
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence

from typing_extensions import Self, override

from susa.core.serializable import JSON, Serializable


def node(
    tag: str,
    elements: Sequence[ET.Element] = (),
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> ET.Element:
    element = ET.Element(tag, dict(sorted((attrs or {}).items())))
    element.text = text
    for other in elements:
        add(element, other)
    return element


# Children are sorted by tag and attributes by name, so that the XML doesn't depend on the order the builders ran in.
def add(parent: ET.Element, element: ET.Element) -> None:
    index = bisect.bisect_right(parent, element.tag, key=lambda other: other.tag)
    parent.insert(index, element)


def attribute(element: ET.Element, name: str, value: str) -> None:
    element.set(name, value)
    element.attrib = dict(sorted(element.attrib.items()))


def child(parent: ET.Element, path: str) -> ET.Element:
    element = parent.find(path)
    assert element is not None, f"There's no {path} in {parent.tag}!"
    return element


def put(parent: ET.Element, element: ET.Element) -> None:
    for other in parent.findall(element.tag):
        parent.remove(other)
    add(parent, element)


class LVModel(Serializable):
    element: ET.Element

    def build(self) -> str:
        ET.indent(self.element)
        return ET.tostring(self.element, encoding="unicode")

    # Models' constructor arguments are all optional.
    @classmethod
    def of(cls, element: ET.Element) -> Self:
        model = cls()
        model.element = element
        return model

    @classmethod
    def parse(cls, xml: str | bytes) -> Self:
        return cls.of(ET.fromstring(xml))

    @override
    def __getstate__(self) -> JSON:
        return {"xml": self.build()}

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, dict) and isinstance(state["xml"], str)
        self.element = ET.fromstring(state["xml"])

    @override
    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and other.build() == self.build()
