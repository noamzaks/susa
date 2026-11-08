from __future__ import annotations

import time
from collections.abc import Sequence

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
from susa.kubevirt._kubectl import (
    create,
    delete,
    deletion,
    kubectl,
    kubectl_guarded,
    random_name,
    virtctl,
    wait,
)
from susa.kubevirt.machine_model import KVMachineModel
from susa.utilities.generic import memory_file


class KVSnapshot(Snapshot):
    API_VERSION = "snapshot.kubevirt.io/v1beta1"

    def __init__(self, machine: KVMachine) -> None:
        self.machine = machine
        self.name = random_name()
        self.was_powered_on = False

    @override
    def create(self) -> None:
        self.was_powered_on = self.machine.is_powered_on
        deleting = deletion("virtualmachinesnapshot", self.name)
        with kubectl_guarded(deleting) as self.guard:
            create(
                {
                    "apiVersion": KVSnapshot.API_VERSION,
                    "kind": "VirtualMachineSnapshot",
                    "metadata": {"name": self.name},
                    "spec": {"source": self._source()},
                }
            )
            wait(
                "virtualmachinesnapshot",
                self.name,
                "jsonpath={.status.readyToUse}=true",
                self.machine.timeout,
            )

    @override
    def destroy(self) -> None:
        self.revert()
        delete("virtualmachinesnapshot", self.name, self.machine.timeout)
        self.guard.cancel()

    @override
    def revert(self) -> None:
        if self.machine.is_powered_on:
            self.machine.power_off()
        name = random_name()
        timeout = self.machine.timeout
        with kubectl_guarded(deletion("virtualmachinerestore", name)) as guard:
            create(
                {
                    "apiVersion": KVSnapshot.API_VERSION,
                    "kind": "VirtualMachineRestore",
                    "metadata": {"name": name},
                    "spec": {
                        "target": self._source(),
                        "virtualMachineSnapshotName": self.name,
                    },
                }
            )
            condition = "jsonpath={.status.complete}=true"
            wait("virtualmachinerestore", name, condition, timeout)
            delete("virtualmachinerestore", name, timeout)
            guard.cancel()
        if self.was_powered_on:
            self.machine.power_on()

    def _source(self) -> dict[str, str]:
        return {
            "apiGroup": "kubevirt.io",
            "kind": "VirtualMachine",
            "name": self.machine.name,
        }


class KVMachine(
    Machine, Snapshottable, Powerable, Screenshottable, SerialAccessible, KeyPressable
):
    VIRSH = "qemu+unix:///session?socket=/var/run/libvirt/virtqemud-sock"

    def __init__(self, model: KVMachineModel, timeout: float = 300) -> None:
        self.model = model
        self.timeout = timeout

    @property
    @override
    def name(self) -> str:
        return self.model.get_name()

    @property
    @override
    def interfaces(self) -> list[Interface]:
        ips = self.model.get_ips()
        path = '{range .status.interfaces[?(@.name)]}{.name}{" "}{.mac}{"\\n"}{end}'
        lines = kubectl("get", "vmi", self.name, f"-o=jsonpath={path}").splitlines()
        return [
            BasicInterface(mac, ips.get(name))
            for name, mac in (line.split() for line in lines)
        ]

    @override
    def create(self) -> None:
        with kubectl_guarded(*self._deletions()) as self.guard:
            for attachment in self.model.get_attachments().values():
                create(attachment)
            for name, script in self.model.get_hooks().items():
                kubectl("create", "configmap", name, f"--from-literal=hook.sh={script}")
            create(self.model.manifest)

    @override
    def destroy(self) -> None:
        delete("virtualmachine", self.name, self.timeout)
        wait("vmi", self.name, "delete", self.timeout)
        for name in self.model.get_attachments():
            delete("network-attachment-definition", name, self.timeout)
        for name in self.model.get_hooks():
            delete("configmap", name, self.timeout)
        self.guard.cancel()

    @override
    def snapshot(self) -> KVSnapshot:
        return KVSnapshot(self)

    @property
    @override
    def is_powered_on(self) -> bool:
        phase = kubectl(
            "get", "vmi", self.name, "--ignore-not-found", "-o=jsonpath={.status.phase}"
        )
        return phase == "Running"

    @override
    def power_on(self) -> None:
        virtctl("start", self.name)
        self.wait_until_running()

    @override
    def power_off(self) -> None:
        virtctl("stop", self.name, "--grace-period=0", "--force")
        wait("vmi", self.name, "delete", self.timeout)

    @override
    def shutdown(self) -> None:
        virtctl("stop", self.name)
        wait("vmi", self.name, "delete", self.timeout)

    @override
    def reboot(self) -> None:
        virtctl("restart", self.name)

    @override
    def reset(self) -> None:
        virtctl("reset", self.name)

    @override
    def screenshot(self) -> Screenshot:
        with memory_file() as file:
            virtctl("vnc", "screenshot", self.name, "-f", str(file))
            return Screenshot(file.read_bytes(), "image/png")

    @override
    def serial(self) -> CommandSerial:
        return CommandSerial(["virtctl", "console", self.name])

    @override
    def press(self, keys: Sequence[Key], hold_time: float = 0.1) -> None:
        pod = kubectl(
            "get",
            "pod",
            f"--selector=vm.kubevirt.io/name={self.name},kubevirt.io=virt-launcher",
            "--field-selector=status.phase=Running",
            "-o=name",
        ).strip()
        kubectl(
            "exec",
            pod,
            "--container=compute",
            "--",
            "virsh",
            "--connect",
            KVMachine.VIRSH,
            "send-key",
            "1",
            "--codeset",
            "linux",
            "--holdtime",
            str(round(hold_time * 1000)),
            *(str(key.value) for key in keys),
        )
        time.sleep(hold_time)

    def wait_until_running(self) -> None:
        wait("virtualmachine", self.name, "condition=Ready", self.timeout)
        wait("vmi", self.name, "jsonpath={.status.interfaces[0].mac}", self.timeout)

    def _deletions(self) -> list[list[str]]:
        return [
            deletion("virtualmachine", self.name),
            *(
                deletion("network-attachment-definition", n)
                for n in self.model.get_attachments()
            ),
            *(deletion("configmap", n) for n in self.model.get_hooks()),
        ]
