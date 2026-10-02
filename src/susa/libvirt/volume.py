from __future__ import annotations

from typing import cast

import libvirt as lv
from typing_extensions import Self, override

from susa.core.resource import Resource
from susa.libvirt.entity import LVEntity, LVEntityState
from susa.libvirt.volume_model import VolumeModel


class LVVolumeState(LVEntityState[VolumeModel]):
    # pydantic doesn't substitute `M` in inherited fields.
    model: VolumeModel
    pool: str


class LVVolume(LVEntity[lv.virStorageVol, VolumeModel], Resource):
    state_type = LVVolumeState

    # Made as a copy of `source` (see `commit`) if given.
    def __init__(
        self,
        model: VolumeModel,
        pool: str = "default",
        source: LVVolume | None = None,
        conn: lv.virConnect | None = None,
    ) -> None:
        super().__init__(model, conn)
        self.pool = pool
        self.source = source

    @property
    def path(self) -> str:
        assert self.value is not None
        return self.value.path()

    @override
    def create(self) -> None:
        assert self.value is None
        pool = self.conn.storagePoolLookupByName(self.pool)
        if self.source is None:
            self.value = pool.createXML(self.xml())
            return

        assert self.source.value is not None
        self.value = pool.createXMLFrom(self.xml(), self.source.value)

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.value.delete()
        self.value = None

    @override
    def lookup(self) -> lv.virStorageVol:
        pool = self.conn.storagePoolLookupByName(self.pool)
        return pool.storageVolLookupByName(self.model.get_name())

    # Its changes, committed to a new (not yet created) volume: a standalone copy of its contents (what's backing it,
    # with its own changes on top), e.g. to keep what a machine wrote to it, or to back new ones.
    def commit(self, model: VolumeModel) -> LVVolume:
        return LVVolume(model, self.pool, self)

    @override
    def serialize(self) -> LVVolumeState:
        return {**super().serialize(), "pool": self.pool}

    @classmethod
    @override
    def restore(cls, state: LVEntityState[VolumeModel]) -> Self:
        volume = cast(LVVolumeState, state)
        result = cls(volume["model"], volume["pool"])
        result.reconnect(volume["uri"])
        return result
