from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import libvirt as lv
from typing_extensions import Self, override

from susa.core.interface import Interface
from susa.core.keyboard import Key, KeyPressable
from susa.core.machine import (
    Machine,
    Powerable,
    Screenshot,
    Screenshottable,
    SerialAccessible,
    Snapshot,
    Snapshottable,
)
from susa.libvirt.entity import LVEntity, LVEntityState
from susa.libvirt.interface import LVInterface
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.serial import LVSerial
from susa.libvirt.stream import LVStream

SCREENSHOT_TIMEOUT = 60


class LVSnapshotState(LVEntityState[SnapshotModel]):
    # pydantic doesn't substitute `M` in inherited fields.
    model: SnapshotModel
    machine: LVMachine


class LVSnapshot(LVEntity[lv.virDomainSnapshot, SnapshotModel], Snapshot):
    state_type = LVSnapshotState

    def __init__(
        self,
        machine: LVMachine,
        model: SnapshotModel | None = None,
        conn: lv.virConnect | None = None,
    ) -> None:
        super().__init__(model=model or SnapshotModel(), conn=conn)

        self.machine = machine

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.machine.domain.snapshotCreateXML(self.xml())

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.revert()
        self.value.delete()
        self.value = None

    @override
    def lookup(self) -> lv.virDomainSnapshot:
        return self.machine.domain.snapshotLookupByName(self.model.get_name())

    @override
    def serialize(self) -> LVSnapshotState:
        return {**super().serialize(), "machine": self.machine}

    @classmethod
    @override
    def restore(cls, state: LVEntityState[SnapshotModel]) -> Self:
        snapshot = cast(LVSnapshotState, state)
        return cls(snapshot["machine"], snapshot["model"]).reconnect(snapshot["uri"])

    @override
    def revert(self) -> None:
        assert self.value is not None
        self.machine.domain.revertToSnapshot(self.value)


class LVMachine(
    LVEntity[lv.virDomain, MachineModel],
    Machine,
    Snapshottable,
    Powerable,
    Screenshottable,
    SerialAccessible,
    KeyPressable,
):
    state_type = LVEntityState[MachineModel]

    @property
    def domain(self) -> lv.virDomain:
        assert self.value is not None, "The machine wasn't created!"
        return self.value

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.conn.defineXML(self.xml())
        self.value.create()

    @override
    def lookup(self) -> lv.virDomain:
        return self.conn.lookupByName(self.name)

    @override
    def destroy(self) -> None:
        if self.domain.isActive():
            self.domain.destroy()

        flags = (
            lv.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            | lv.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
        )
        if self.model.get_nvram() is not None:
            # The UEFI variables file belongs to whoever built the model, so leave it alone.
            flags |= lv.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM
        self.domain.undefineFlags(flags)
        self.value = None

    @property
    @override
    def interfaces(self) -> list[Interface]:
        result: list[Interface] = []
        for interface in self.model.get_interfaces():
            mac = interface.get_mac()
            network = interface.get_network()
            ip = None
            if network is not None:
                xml = self.conn.networkLookupByName(network).XMLDesc()
                ip = NetworkModel.parse(xml).get_ip(mac)
            result.append(LVInterface(mac, ip))
        return result

    @override
    def snapshot(self) -> LVSnapshot:
        return LVSnapshot(machine=self)

    @property
    @override
    def is_powered_on(self) -> bool:
        return bool(self.domain.isActive())

    @override
    def power_on(self) -> None:
        self.domain.create()

    @override
    def power_off(self) -> None:
        self.domain.destroy()

    @override
    def shutdown(self) -> None:
        self.domain.shutdown()

    @override
    def reboot(self) -> None:
        self.domain.reboot()

    @override
    def reset(self) -> None:
        self.domain.reset()

    @override
    def screenshot(self) -> Screenshot:
        stream = LVStream(self.conn)
        mime_type = self.domain.screenshot(stream.stream, 0)
        data = stream.read_all(SCREENSHOT_TIMEOUT)
        stream.close()
        return Screenshot(data=data, mime_type=mime_type)

    @override
    def serial(self) -> LVSerial:
        return LVSerial(self)

    @override
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None:
        key_codes = [key.value for key in keys]
        self.domain.sendKey(
            lv.VIR_KEYCODE_SET_LINUX,
            round(hold_time * 1000),
            key_codes,
            len(key_codes),
            0,
        )
