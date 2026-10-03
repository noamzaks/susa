from __future__ import annotations

import platform
import re
from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from susa.libvirt.arch import ARCH_DEFAULTS
from susa.libvirt.disk_model import DiskModel
from susa.libvirt.interface_model import InterfaceModel
from susa.libvirt.machine_model import MachineModel, SnapshotModel
from susa.libvirt.network_model import NetworkModel
from susa.utilities.generic import GIGA

MAC = "52:54:00:12:34:56"


def hosts(network: NetworkModel) -> dict[str | None, str]:
    return {host.mac: host.ip for host in network.get_hosts() or []}


# Keep the XML independent of the machine the tests run on.
@pytest.fixture(autouse=True)
def fake_host_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")


@pytest.fixture(autouse=True)
def fake_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cwd = Path("/fake/cwd")

    def resolve(self: Path, strict: bool = False) -> Path:
        return self if self.is_absolute() else fake_cwd / self

    monkeypatch.setattr(Path, "resolve", resolve)


def test_machine_model_empty(snapshot: Snapshot) -> None:
    xml = MachineModel("test").build()
    snapshot.assert_match(xml, "domain.xml")


def test_network_model_empty(snapshot: Snapshot) -> None:
    xml = NetworkModel("test").build()
    snapshot.assert_match(xml, "network.xml")


def test_interface_model_empty(snapshot: Snapshot) -> None:
    xml = InterfaceModel(mac=MAC).build()
    snapshot.assert_match(xml, "interface.xml")


def test_disk_model_empty(snapshot: Snapshot) -> None:
    xml = DiskModel().build()
    snapshot.assert_match(xml, "disk.xml")


def test_snapshot_model_empty(snapshot: Snapshot) -> None:
    xml = SnapshotModel("test").build()
    snapshot.assert_match(xml, "snapshot.xml")


@pytest.mark.parametrize("arch", ARCH_DEFAULTS)
def test_machine_model_default(snapshot: Snapshot, arch: str) -> None:
    disk = DiskModel().source("somewhere")
    xml = MachineModel("test").arch(arch).default().disk(disk).build()
    snapshot.assert_match(xml, "domain.xml")


@pytest.mark.parametrize("arch", ARCH_DEFAULTS)
def test_machine_model_default_interface(snapshot: Snapshot, arch: str) -> None:
    interface = InterfaceModel(mac=MAC)
    NetworkModel("test").default().interface(interface)
    xml = MachineModel("test").arch(arch).default().interface(interface).build()
    snapshot.assert_match(xml, "domain.xml")


def test_network_model_default(snapshot: Snapshot) -> None:
    xml = NetworkModel("test").default().build()
    snapshot.assert_match(xml, "network.xml")


def test_interface_model_with_model(snapshot: Snapshot) -> None:
    xml = InterfaceModel(mac=MAC).model("virtio").build()
    snapshot.assert_match(xml, "interface.xml")


@pytest.mark.parametrize("ip", ("10.0.0.1", "10.0.0.2", "10.0.0.254"))
def test_network_model_with_ip(snapshot: Snapshot, ip: str) -> None:
    xml = NetworkModel("test").default().ip(ip).build()
    snapshot.assert_match(xml, "network.xml")


def test_disk_model_with_source(snapshot: Snapshot) -> None:
    xml = DiskModel().source("somewhere").build()
    snapshot.assert_match(xml, "disk.xml")


def test_machine_model_full(snapshot: Snapshot) -> None:
    interface = InterfaceModel(mac=MAC)
    NetworkModel("test").default().ip("10.0.0.1").interface(interface, "10.0.0.10")
    disk = DiskModel().source("somewhere")
    xml = (
        MachineModel("test")
        .arch("x86_64")
        .default()
        .memory(4 * GIGA)
        .cpu(2)
        .efi()
        .kernel("vmlinux", "initrd.gz", "console=ttyS0 root=/dev/sda1")
        .interface(interface)
        .disk(disk)
        .disk(disk)
        .build()
    )
    snapshot.assert_match(xml, "domain.xml")


def test_interface_model_random_mac() -> None:
    macs = set()
    for _ in range(10):
        mac = InterfaceModel().get_mac()
        assert re.fullmatch(r"52:54:00(:[0-9a-f]{2}){3}", mac)
        macs.add(mac)
    # 10 random 24-bit suffixes colliding is (practically) impossible.
    assert len(macs) > 1


def test_interface_model_parse_keeps_mac() -> None:
    xml = InterfaceModel(mac=MAC).model("e1000").build()
    assert InterfaceModel.parse(xml).get_mac() == MAC


@pytest.mark.parametrize("arch", ARCH_DEFAULTS)
def test_machine_model_interface_default_nic(arch: str) -> None:
    machine = MachineModel("test").arch(arch).interface(InterfaceModel(mac=MAC))
    [interface] = machine.get_interfaces() or []
    assert interface.model is not None
    assert interface.model.type == ARCH_DEFAULTS[arch].nic


def test_network_model_interface_without_ip(snapshot: Snapshot) -> None:
    interface = InterfaceModel(mac=MAC)
    network = NetworkModel("test").default()
    network.interface(interface)
    assert interface.xml_model.source is not None
    assert interface.xml_model.source.network == "test"
    snapshot.assert_match(network.build(), "network.xml")


def test_network_model_interface_without_dhcp_rejects_ip() -> None:
    network = NetworkModel("test").default().ip("10.0.0.1", dhcp=False)
    with pytest.raises(AssertionError):
        network.interface(InterfaceModel(mac=MAC), "10.0.0.10")


def test_network_model_interface_with_ip(snapshot: Snapshot) -> None:
    interface = InterfaceModel(mac=MAC)
    network = NetworkModel("test").default().ip("10.0.0.1")
    assert network.interface(interface, "10.0.0.10") is network
    assert interface.xml_model.source is not None
    assert interface.xml_model.source.network == "test"
    assert hosts(network) == {MAC: "10.0.0.10"}
    snapshot.assert_match(network.build(), "network.xml")


def test_network_model_interface_picks_free_ips() -> None:
    network = NetworkModel("test").default().ip("10.0.0.1")
    network.interface(InterfaceModel(mac="52:54:00:00:00:01"), "10.0.0.3")
    network.interface(InterfaceModel(mac="52:54:00:00:00:02"))
    network.interface(InterfaceModel(mac="52:54:00:00:00:03"))
    network.interface(InterfaceModel(mac="52:54:00:00:00:04"))
    assert hosts(network) == {
        "52:54:00:00:00:01": "10.0.0.3",
        # The gateway (10.0.0.1) isn't in the DHCP range, and 10.0.0.3 is taken.
        "52:54:00:00:00:02": "10.0.0.2",
        "52:54:00:00:00:03": "10.0.0.4",
        "52:54:00:00:00:04": "10.0.0.5",
    }


def test_network_model_interface_picks_ip_below_gateway() -> None:
    network = NetworkModel("test").default().ip("10.0.0.254")
    network.interface(InterfaceModel(mac=MAC))
    assert hosts(network) == {MAC: "10.0.0.1"}


def test_network_model_interface_no_free_ip() -> None:
    # A /30 has only 2 hosts, one of which is the gateway.
    network = NetworkModel("test").default().ip("10.0.0.1", "255.255.255.252")
    network.interface(InterfaceModel(mac="52:54:00:00:00:01"))
    assert hosts(network) == {"52:54:00:00:00:01": "10.0.0.2"}
    with pytest.raises(RuntimeError):
        network.interface(InterfaceModel(mac="52:54:00:00:00:02"))


def test_machine_model_interface_keeps_address() -> None:
    interface = InterfaceModel(mac=MAC)
    domain = MachineModel("test").arch("mips").default().interface(interface)
    assert interface.xml_model.address is not None
    assert interface.xml_model.address.slot == 12

    # An address that's already set isn't overridden.
    other = InterfaceModel.parse(interface.build())
    assert other.xml_model.address is not None
    other.xml_model.address.slot = 5
    domain.interface(other)
    assert other.xml_model.address.slot == 5


def test_interface_model_getters() -> None:
    interface = InterfaceModel(mac=MAC)
    assert interface.get_mac() == MAC
    assert interface.get_network() is None

    assert interface.network("test") is interface
    assert interface.get_network() == "test"


def test_network_model_getters() -> None:
    network = NetworkModel("test")
    assert network.get_name() == "test"
    assert hosts(network) == {}
    assert hosts(network).get(MAC) is None

    network.ip("10.0.0.1")
    assert hosts(network) == {}

    network.interface(InterfaceModel(mac=MAC), "10.0.0.10")
    network.interface(InterfaceModel(mac="52:54:00:00:00:01"))
    assert hosts(network) == {MAC: "10.0.0.10", "52:54:00:00:00:01": "10.0.0.2"}
    assert hosts(network).get(MAC) == "10.0.0.10"
    assert hosts(network).get("52:54:00:00:00:02") is None


def test_network_model_getters_after_parse() -> None:
    network = NetworkModel("test").ip("10.0.0.1")
    network.interface(InterfaceModel(mac=MAC), "10.0.0.10")
    parsed = NetworkModel.parse(network.build())
    assert parsed.get_name() == "test"
    assert hosts(parsed).get(MAC) == "10.0.0.10"


def test_machine_model_getters() -> None:
    domain = MachineModel("test").arch("x86_64").default()
    assert domain.get_name() == "test"
    assert domain.get_arch() == "x86_64"
    assert domain.get_interfaces() == []

    domain.interface(InterfaceModel(mac=MAC)).interface(
        InterfaceModel(mac="52:54:00:00:00:01")
    )
    assert [i.mac.address for i in domain.get_interfaces() or [] if i.mac] == [
        MAC,
        "52:54:00:00:00:01",
    ]


def test_machine_model_get_arch_unset() -> None:
    with pytest.raises(AssertionError):
        MachineModel("test").get_arch()


def test_snapshot_model_getters() -> None:
    assert SnapshotModel("test").get_name() == "test"


@pytest.mark.parametrize("arch", ARCH_DEFAULTS)
def test_machine_model_parse(arch: str) -> None:
    xml = MachineModel("test").arch(arch).default().qemu_args(["-cpu", "max"]).build()
    assert MachineModel.parse(xml).build() == xml
