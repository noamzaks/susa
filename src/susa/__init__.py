import logging
import random
import string
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Self

import IPython
import libvirt as lv
import pydantic_libvirt.domain as lvdomain
import pydantic_libvirt.network as lvnetwork


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


class Connection:
    _current: Connection | None = None

    def __init__(self, uri: str | None = None) -> None:
        self.uri = uri
        self.conn: lv.virConnect | None = None

    def __enter__(self) -> lv.virConnect:
        if self.conn is not None:
            raise ValueError("Cannot open an already opened connection!")

        if Connection._current is None:
            Connection._current = self

        self.conn = lv.open(self.uri)
        return self.conn

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if Connection._current is self:
            Connection._current = None

        if self.conn is None:
            return

        self.conn.close()
        self.conn = None

    @staticmethod
    def current() -> Connection:
        if Connection._current is None:
            raise ValueError(
                "Cannot get current libvirt connection as there isn't any!"
            )

        return Connection._current

    @staticmethod
    def current_conn() -> lv.virConnect:
        c = Connection.current()
        assert c.conn is not None
        return c.conn


class Network:
    def __init__(self) -> None:
        name = f"susa-{random_id(10)}"
        self.spec = lvnetwork.network(
            name=lvnetwork.name(value=name),
            bridge=lvnetwork.bridge(name=name, stp="off", delay=0),
            ip_list=[
                lvnetwork.ip(
                    address="10.0.0.1",
                    netmask="255.255.255.0",
                    dhcp=lvnetwork.dhcp(
                        range_list=[
                            lvnetwork.range(start="10.0.0.2", end="10.0.0.254"),
                        ]
                    ),
                ),
            ],
        )
        self.network: lv.virNetwork | None = None

    def __enter__(self) -> Self:
        if self.network is not None:
            raise ValueError("Cannot create already created network!")

        conn = Connection.current_conn()

        tree = self.spec.to_xml_tree(skip_empty=True)
        ET.indent(tree)
        xml = ET.tostring(tree, encoding="unicode")
        logging.info(f"Creating network {self.name}\n{xml}")

        self.network = conn.networkCreateXML(xml)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.network is not None
        self.network.destroy()
        self.network = None

    @property
    def name(self) -> str:
        return self.spec.name.value  # type: ignore[no-any-return]


class Interface:
    def __init__(self, network: Network | None = None):
        self.spec = lvdomain.devices_interface(
            type="network",
            model=lvdomain.interface_options_model(type="virtio"),
        )

        if network is not None:
            self.set_network(network)

    def set_network(self, network: Network) -> None:
        self.spec.source = lvdomain.interface_source(network=network.name)


class Disk:
    def __init__(self, path: Path) -> None:
        self.spec = lvdomain.disk(
            type="file",
            device="disk",
            driver=lvdomain.disk_driver(name="qemu", type="qcow2"),
            source=lvdomain.devices_disk_source(file=str(path.resolve())),
            target=lvdomain.disk_target(dev="sda"),
        )

    @property
    def path(self) -> Path:
        assert self.spec.source is not None and self.spec.source.file is not None
        return Path(self.spec.source.file)


class LinkedCloneDisk(Disk):
    def __init__(self, source: Disk, path: Path) -> None:
        super().__init__(path)

        self.source = source.path

        subprocess.run(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-b",
                source.path,
                "-B",
                "qcow2",
                self.path,
            ],
            check=True,
        )

    def commit(self) -> None:
        subprocess.run(["qemu-img", "commit", self.path], check=True)


class Machine:
    def __init__(
        self, interfaces: list[Interface] | None = None, disks: list[Disk] | None = None
    ) -> None:
        self.spec = lvdomain.domain(
            type="kvm",
            name=lvdomain.name(value=f"susa-{random_id(10)}"),
            memory=lvdomain.resources_memory(value=2, unit="GiB"),
            vcpu=lvdomain.resources_vcpu(value=2),
            os=lvdomain.os(
                type=lvdomain.os_type(value="hvm", arch="x86_64", machine="pc")
            ),
            features=lvdomain.features(
                acpi=lvdomain.features_acpi(),
                apic=lvdomain.apic(),
                vmport=lvdomain.vmport(state="off"),
            ),
            cpu=lvdomain.guestcpu(
                mode="host-passthrough", check="none", migratable="on"
            ),
            devices=lvdomain.devices(
                video_list=[
                    lvdomain.video(model=lvdomain.video_model(type="vga")),
                ],
                graphics_list=[
                    lvdomain.graphics(type="vnc", port=-1),
                ],
                input_list=[
                    lvdomain.devices_input(type="mouse", bus="ps2"),
                    lvdomain.devices_input(type="keyboard", bus="ps2"),
                ],
                disk_list=[],
                interface_list=[],
            ),
        )
        self.domain: lv.virDomain | None = None

        for interface in interfaces or []:
            self.add_interface(interface)

        for disk in disks or []:
            self.add_disk(disk)

    def __enter__(self) -> Self:
        if self.domain is not None:
            raise ValueError("Cannot create already created machine!")

        conn = Connection.current_conn()

        tree = self.spec.to_xml_tree(skip_empty=True)
        ET.indent(tree)
        xml = ET.tostring(tree, encoding="unicode")
        logging.info(f"Creating domain {self.name}\n{xml}")

        self.domain = conn.createXML(xml)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.domain is not None
        self.domain.destroy()
        self.domain = None

    @property
    def name(self) -> str:
        return self.spec.name.value  # type: ignore[no-any-return]

    def add_interface(self, interface: Interface) -> None:
        assert (
            self.spec.devices is not None
            and self.spec.devices.interface_list is not None
        )
        self.spec.devices.interface_list.append(interface.spec)

    def add_disk(self, disk: Disk) -> None:
        assert self.spec.devices is not None and self.spec.devices.disk_list is not None

        spec = disk.spec.model_copy()
        spec.target = lvdomain.disk_target(dev="sda", bus="virtio")

        self.spec.devices.disk_list.append(spec)


@contextmanager
def tmp_dir_path() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    disk = Disk(Path("fun.qcow2"))

    with tmp_dir_path() as d:
        clone = LinkedCloneDisk(disk, d / "disk.qcow2")

        with (
            Connection(),
            Network() as n,
            Machine(
                interfaces=[Interface(n)],
                disks=[clone],
            ) as m,
        ):
            print(m)
            IPython.embed(colors="linux")
