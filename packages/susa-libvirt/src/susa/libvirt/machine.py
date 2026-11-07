from __future__ import annotations

import json
import re
import tempfile
import time
import xml.etree.ElementTree as ET
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
from susa.core.saveable import Saveable
from susa.core.serializable import JSON, deserialize, serialize
from susa.libvirt._virsh import virsh, virsh_command, virsh_data, virsh_xml
from susa.libvirt.entity import LVEntity
from susa.libvirt.interface_model import LVInterfaceModel
from susa.libvirt.machine_model import LVMachineModel, LVSnapshotModel
from susa.libvirt.network_model import LVNetworkModel
from susa.utilities.generic import run


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

    @override
    def __getstate__(self) -> JSON:
        state = super().__getstate__()
        assert isinstance(state, dict)
        return {**state, "machine": serialize(self.machine)}

    @override
    def __setstate__(self, state: JSON) -> None:
        super().__setstate__(state)
        assert isinstance(state, dict)
        machine = deserialize(state["machine"])
        assert isinstance(machine, LVMachine)
        self.machine = machine


class LVMachine(
    LVEntity[LVMachineModel],
    Machine,
    Snapshottable,
    Powerable,
    Screenshottable,
    SerialAccessible,
    KeyPressable,
    Saveable,
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

    # Its memory (if it's running) and its volumes' contents, which are saved while it's stopped (for its memory),
    # so they're as the memory has them. The memory is saved to a volume of its first volume's pool, which libvirt
    # hands over.
    @override
    def save(self) -> JSON:
        if not self.is_powered_on:
            return {"memory": None, "volumes": self._save_volumes()}
        pool, name = self._memory_volume()
        path = f"{_pool_path(pool)}/{name}"
        virsh("save", self.name, path, "--image-format", "zstd")
        try:
            volumes = self._save_volumes()
            virsh("pool-refresh", pool)
            memory = virsh_data("vol-download", "--pool", pool, name, "/dev/stdout")
        finally:
            virsh("restore", path)
            virsh("vol-delete", "--pool", pool, name)
        return {"memory": memory.hex(), "volumes": volumes}

    # Into its volumes, which must be created already. libvirt restores a memory only with the XML it was saved with.
    @override
    def restore(self, state: JSON) -> None:
        assert isinstance(state, dict)
        volumes, memory = state["volumes"], state["memory"]
        assert isinstance(volumes, list)
        for volume in volumes:
            assert isinstance(volume, dict)
            pool, name, contents = volume["pool"], volume["name"], volume["contents"]
            assert isinstance(pool, str) and isinstance(name, str)
            assert isinstance(contents, str)
            data = bytes.fromhex(contents)
            virsh_data("vol-upload", "--pool", pool, name, "/dev/stdin", data=data)
        if memory is None:
            virsh_xml(self._xml(), "define")
            return
        assert isinstance(memory, str)
        data = bytes.fromhex(memory)
        pool, name = self._memory_volume()
        virsh("vol-create-as", pool, name, str(len(data)), "--format", "raw")
        try:
            virsh_data("vol-upload", "--pool", pool, name, "/dev/stdin", data=data)
            path = virsh("vol-path", "--pool", pool, name).strip()
            virsh_xml(virsh("save-image-dumpxml", path), "define")
            virsh("restore", path)
        finally:
            virsh("vol-delete", "--pool", pool, name)

    def _save_volumes(self) -> JSON:
        return [
            {"pool": pool, "name": name, "contents": _volume_contents(pool, name).hex()}
            for pool, name in self.model.get_volumes()
        ]

    def _memory_volume(self) -> tuple[str, str]:
        volumes = self.model.get_volumes()
        pool = volumes[0][0] if volumes else "default"
        return pool, f"{self.name}.memory"

    def _reserved_ip(self, interface: LVInterfaceModel) -> str | None:
        network = interface.get_network()
        if network is None:
            return None

        xml = virsh("net-dumpxml", network)
        return LVNetworkModel.parse(xml).get_hosts().get(interface.get_mac())


def _pool_path(pool: str) -> str:
    path = ET.fromstring(virsh("pool-dumpxml", pool)).findtext("target/path")
    assert path is not None
    return path


# Without internal snapshots (which hold whole memories), dropped without opening its backing image, which may not be on
# this system.
def _volume_contents(pool: str, name: str) -> bytes:
    data = virsh_data("vol-download", "--pool", pool, name, "/dev/stdout")
    if not data.startswith(b"QFI\xfb"):
        return data
    with tempfile.NamedTemporaryFile() as file:
        file.write(data)
        file.flush()
        options = {"file": {"driver": "file", "filename": file.name}, "backing": None}
        image = "json:" + json.dumps({"driver": "qcow2", **options})
        info = json.loads(run(["qemu-img", "info", "--output=json", image]))
        for snapshot in info.get("snapshots", []):
            run(["qemu-img", "snapshot", "-d", snapshot["name"], image])
        return Path(file.name).read_bytes()
