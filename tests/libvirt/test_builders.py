import pytest
from pytest_snapshot.plugin import Snapshot

from susa.libvirt.builders import (
    DiskBuilder,
    DomainBuilder,
    InterfaceBuilder,
    NetworkBuilder,
    SnapshotBuilder,
)
from susa.utilities import GIGA


def test_domain_builder_empty(snapshot: Snapshot) -> None:
    xml = DomainBuilder("test").build()
    snapshot.assert_match(xml, "domain.xml")


def test_network_builder_empty(snapshot: Snapshot) -> None:
    xml = NetworkBuilder("test").build()
    snapshot.assert_match(xml, "network.xml")


def test_interface_builder_empty(snapshot: Snapshot) -> None:
    xml = InterfaceBuilder().build()
    snapshot.assert_match(xml, "interface.xml")


def test_disk_builder_empty(snapshot: Snapshot) -> None:
    xml = DiskBuilder().build()
    snapshot.assert_match(xml, "disk.xml")


def test_snapshot_builder_empty(snapshot: Snapshot) -> None:
    xml = SnapshotBuilder("test").build()
    snapshot.assert_match(xml, "snapshot.xml")


@pytest.mark.parametrize(
    "arch", ("x86_64", "aarch64", "mips", "ppc64le", "armv7l", "riscv64")
)
def test_domain_builder_default(snapshot: Snapshot, arch: str) -> None:
    disk_xml = DiskBuilder().source("somewhere").build()
    xml = DomainBuilder("test").arch(arch).default().disk(disk_xml).build()
    snapshot.assert_match(xml, "domain.xml")


@pytest.mark.parametrize(
    "arch", ("x86_64", "aarch64", "mips", "ppc64le", "armv7l", "riscv64")
)
def test_domain_builder_default_interface(snapshot: Snapshot, arch: str) -> None:
    network_xml = NetworkBuilder("test").default().build()
    xml = DomainBuilder("test").arch(arch).default().interface(network_xml).build()
    snapshot.assert_match(xml, "domain.xml")


def test_network_builder_default(snapshot: Snapshot) -> None:
    xml = NetworkBuilder("test").default().build()
    snapshot.assert_match(xml, "network.xml")


def test_interface_builder_default(snapshot: Snapshot) -> None:
    xml = InterfaceBuilder().default().build()
    snapshot.assert_match(xml, "interface.xml")


@pytest.mark.parametrize("ip", ("10.0.0.1", "10.0.0.2", "10.0.0.254"))
def test_network_builder_with_ip(snapshot: Snapshot, ip: str) -> None:
    xml = NetworkBuilder("test").default().ip(ip).build()
    snapshot.assert_match(xml, "network.xml")


def test_disk_builder_with_source(snapshot: Snapshot) -> None:
    xml = DiskBuilder().source("somewhere").build()
    snapshot.assert_match(xml, "disk.xml")


def test_domain_builder_full(snapshot: Snapshot) -> None:
    network_xml = NetworkBuilder("test").default().build()
    disk_xml = DiskBuilder().source("somewhere").build()
    xml = (
        DomainBuilder("test")
        .arch("x86_64")
        .default()
        .memory(4 * GIGA)
        .cpu(2)
        .efi("loader", "nvram")
        .kernel("vmlinux", "initrd.gz", "console=ttyS0 root=/dev/sda1")
        .interface(network_xml)
        .disk(disk_xml)
        .disk(disk_xml)
        .build()
    )
    snapshot.assert_match(xml, "domain.xml")
