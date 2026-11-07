from __future__ import annotations

from pathlib import Path

from typing_extensions import Self, override

from susa.core.communicator import HOST, CommandRunner
from susa.core.serializable import JSON
from susa.libvirt.model import LVModel, child, node, put
from susa.utilities.generic import random_id


class LVVolumeModel(LVModel):
    def __init__(self, name: str | None = None) -> None:
        self.element = node(
            "volume",
            elements=[
                node("name", text=name or f"susa-{random_id(10)}"),
                node("target", elements=[node("format", attrs={"type": "qcow2"})]),
            ],
        )
        # The volume's XML doesn't say which pool it's in.
        self.pool_name = "default"

    def name(self, name: str) -> Self:
        put(self.element, node("name", text=name))

        return self

    def pool(self, pool: str) -> Self:
        self.pool_name = pool

        return self

    def capacity(self, capacity: int) -> Self:
        put(self.element, node("capacity", attrs={"unit": "B"}, text=str(capacity)))

        return self

    # Of the file libvirt creates for it.
    def owner(self, uid: int, gid: int) -> Self:
        permissions = node(
            "permissions",
            elements=[node("owner", text=str(uid)), node("group", text=str(gid))],
        )
        put(child(self.element, "target"), permissions)

        return self

    def backing(self, image: str | Path) -> Self:
        put(
            self.element,
            node(
                "backingStore",
                elements=[
                    node("path", text=str(Path(image).resolve())),
                    node("format", attrs={"type": "qcow2"}),
                ],
            ),
        )

        return self

    # Its file is owned by whom commands on the host run as, so they can open it (e.g. to commit it).
    def default(self, host: CommandRunner | None = None) -> Self:
        host = host or HOST.get()
        return self.owner(int(host.check("id -u")), int(host.check("id -g")))

    # Its pool too, which its XML doesn't say.
    @override
    def __getstate__(self) -> JSON:
        state = super().__getstate__()
        assert isinstance(state, dict)
        return {**state, "pool": self.pool_name}

    @override
    def __setstate__(self, state: JSON) -> None:
        super().__setstate__(state)
        assert isinstance(state, dict) and isinstance(state["pool"], str)
        self.pool_name = state["pool"]

    def get_name(self) -> str:
        name = child(self.element, "name").text
        assert name is not None
        return name

    def get_pool(self) -> str:
        return self.pool_name
