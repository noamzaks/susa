from __future__ import annotations

from collections.abc import Iterable

import libvirt as lv
from typing_extensions import override

from susa.core.interface import Interface
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
from susa.libvirt.interface import LVInterface
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network import LVNetwork
from susa.libvirt.serial import LVSerial


class LVSnapshot(LVEntity[lv.virDomainSnapshot, SnapshotModel], Snapshot):
    def __init__(
        self,
        machine: LVMachine,
        model: SnapshotModel | None = None,
        conn: lv.virConnect | None = None,
    ) -> None:
        super().__init__(model=model or SnapshotModel(), conn=conn)

        self.machine = machine

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @override
    def create(self) -> None:
        if self.value is None:
            assert self.machine.value is not None
            self.value = self.machine.value.snapshotCreateXML(self.build())

    @override
    def destroy(self) -> None:
        assert self.value is not None
        self.revert()

        self.value = None

    @override
    def revert(self) -> None:
        assert self.value is not None and self.machine.value is not None
        self.machine.value.revertToSnapshot(self.value)


class LVMachine(
    LVEntity[lv.virDomain, MachineModel],
    Machine,
    Snapshottable,
    Powerable,
    Screenshottable,
    SerialAccessible,
):
    """A persistent libvirt domain: `create` defines and powers it on, `destroy` powers it off and undefines it.
    (A transient domain would disappear on power off, so it couldn't be powered on again.)"""

    def __init__(
        self,
        model: MachineModel,
        networks: Iterable[LVNetwork] = (),
        conn: lv.virConnect | None = None,
    ) -> None:
        """`networks` are the networks the machine's interfaces are connected to, which know their IPs."""
        super().__init__(model=model, conn=conn)

        self.networks = {n.name: n for n in networks}

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
        self.value = self.conn.defineXML(self.build())
        self.value.create()

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
            network = self.networks.get(interface.get_network() or "")
            ip = network.model.get_ip(mac) if network is not None else None
            result.append(LVInterface(mac, ip))
        return result

    @override
    def snapshot(self) -> LVSnapshot:
        result = LVSnapshot(machine=self)
        result.create()
        return result

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
        stream = self.conn.newStream()
        mime_type = self.domain.screenshot(stream, 0)
        data = b""
        while chunk := stream.recv(1 << 20):
            data += chunk
        stream.finish()
        return Screenshot(data=data, mime_type=mime_type)

    @override
    def serial(self) -> LVSerial:
        result = LVSerial(domain=self.domain, conn=self.conn)
        result.create()
        return result
