from __future__ import annotations

import time
from collections.abc import Sequence

import libvirt as lv
from typing_extensions import override

from susa.core.interface import BasicInterface, Interface
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
from susa.libvirt.entity import LVEntity
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network_model import NetworkModel
from susa.libvirt.serial import LVSerial
from susa.libvirt.stream import LVStream


class LVSnapshot(LVEntity[lv.virDomainSnapshot, SnapshotModel], Snapshot):
    def __init__(
        self,
        machine: LVMachine,
        model: SnapshotModel | None = None,
    ) -> None:
        super().__init__(model or SnapshotModel())
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
    def __init__(self, model: MachineModel) -> None:
        super().__init__(model)

    @property
    def domain(self) -> lv.virDomain:
        assert self.value is not None, "The machine wasn't created!"
        return self.value

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        models = [
            InterfaceModel(xml_model=i) for i in self.model.get_interfaces() or []
        ]
        return [BasicInterface(m.get_mac(), self.reserved_ip(m)) for m in models]

    @override
    def create(self) -> None:
        assert self.value is None
        self.value = self.conn.defineXML(self.xml())
        self.value.create()

    @override
    def destroy(self) -> None:
        if self.is_powered_on:
            self.power_off()

        flags = (
            lv.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            | lv.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
        )
        if self.model.get_firmware() == "efi":
            flags |= lv.VIR_DOMAIN_UNDEFINE_NVRAM
        self.domain.undefineFlags(flags)
        self.value = None

    @override
    def lookup(self) -> lv.virDomain:
        return self.conn.lookupByName(self.name)

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
        data = stream.read_all()
        stream.close()
        return Screenshot(data, mime_type)

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
        # libvirt returns before they're released, and the next keys would queue up behind them.
        time.sleep(hold_time)

    def reserved_ip(self, interface: InterfaceModel) -> str | None:
        network = interface.get_network()
        if network is None:
            return None

        xml = self.conn.networkLookupByName(network).XMLDesc()
        hosts = NetworkModel.parse(xml).get_hosts() or []
        return next((h.ip for h in hosts if h.mac == interface.get_mac()), None)
