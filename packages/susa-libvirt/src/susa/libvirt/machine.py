from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from typing_extensions import override

from susa.core.interface import BasicInterface, Interface
from susa.core.keyboard import Key, KeyPressable
from susa.core.machine import (
    CommandSerial,
    Machine,
    Powerable,
    Screenshot,
    Screenshottable,
    SerialAccessible,
    Snapshot,
    Snapshottable,
)
from susa.libvirt._virsh import virsh, virsh_command, virsh_xml
from susa.libvirt.entity import LVEntity
from susa.libvirt.interface_model import LVInterfaceModel
from susa.libvirt.machine_model import LVMachineModel, LVSnapshotModel
from susa.libvirt.network_model import LVNetworkModel


class LVSnapshot(LVEntity[LVSnapshotModel], Snapshot):
    def __init__(
        self,
        machine: LVMachine,
        model: LVSnapshotModel | None = None,
    ) -> None:
        super().__init__(model or LVSnapshotModel())
        self.machine = machine

    @override
    def create(self) -> None:
        virsh_xml(self._xml(), "snapshot-create", self.machine.name, "--xmlfile")

    @override
    def destroy(self) -> None:
        self.revert()
        virsh("snapshot-delete", self.machine.name, self.model.get_name())

    @override
    def revert(self) -> None:
        virsh("snapshot-revert", self.machine.name, self.model.get_name())


class LVMachine(
    LVEntity[LVMachineModel],
    Machine,
    Snapshottable,
    Powerable,
    Screenshottable,
    SerialAccessible,
    KeyPressable,
):
    def __init__(self, model: LVMachineModel) -> None:
        super().__init__(model)

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        return [
            BasicInterface(i.get_mac(), self._reserved_ip(i))
            for i in self.model.get_interfaces()
        ]

    @override
    def create(self) -> None:
        virsh_xml(self._xml(), "define")
        virsh("start", self.name)

    @override
    def destroy(self) -> None:
        if self.is_powered_on:
            self.power_off()

        flags = ["--managed-save", "--snapshots-metadata"]
        if self.model.get_firmware() == "efi":
            flags.append("--nvram")
        virsh("undefine", self.name, *flags)

    @override
    def snapshot(self) -> LVSnapshot:
        return LVSnapshot(machine=self)

    @property
    @override
    def is_powered_on(self) -> bool:
        return self.name in virsh("list", "--name").split()

    @override
    def power_on(self) -> None:
        virsh("start", self.name)

    @override
    def power_off(self) -> None:
        virsh("destroy", self.name)

    @override
    def shutdown(self) -> None:
        virsh("shutdown", self.name)

    @override
    def reboot(self) -> None:
        virsh("reboot", self.name)

    @override
    def reset(self) -> None:
        virsh("reset", self.name)

    @override
    def screenshot(self) -> Screenshot:
        with tempfile.NamedTemporaryFile() as file:
            output = virsh("screenshot", self.name, "--file", file.name)
            match = re.search(r"type of (\S+)", output)
            assert match is not None, output
            return Screenshot(Path(file.name).read_bytes(), match[1])

    @override
    def serial(self) -> CommandSerial:
        return CommandSerial(virsh_command("console", self.name))

    @override
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None:
        hold = str(round(hold_time * 1000))
        codes = [str(key.value) for key in keys]
        virsh("send-key", self.name, "--codeset", "linux", "--holdtime", hold, *codes)
        # libvirt returns before they're released, and the next keys would queue up behind them.
        time.sleep(hold_time)

    def _reserved_ip(self, interface: LVInterfaceModel) -> str | None:
        network = interface.get_network()
        if network is None:
            return None

        xml = virsh("net-dumpxml", network)
        return LVNetworkModel.parse(xml).get_hosts().get(interface.get_mac())
