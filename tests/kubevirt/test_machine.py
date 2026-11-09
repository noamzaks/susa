from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from scapy.layers.inet import ICMP, IP

from susa.communicators.ssh import SSHCommunicator
from susa.core.keyboard import Key
from susa.core.machine import wait_until_booted
from susa.kubevirt import (
    KVMachine,
    KVMachineModel,
    KVNetwork,
    KVNetworkModel,
    KVNodePod,
    KVSniffer,
    KVVolume,
    KVVolumeModel,
)
from susa.kubevirt._kubectl import Manifest, create, kubectl, random_name
from susa.kubevirt.emulation import aarch64_without_kvm_script
from susa.utilities.generic import GIGA, wait_until
from susa.utilities.networking import ping

GOLDEN = "debian"
BOOT_TIMEOUT = 600
STORAGE_CLASS = "csi-hostpath-sc"
HOST_IP = "10.77.0.1"
GUEST_IP = "10.77.0.5"
PEER_IP = "10.77.0.9"


@pytest.fixture(scope="module", autouse=True)
def golden() -> None:
    if shutil.which("kubectl") is None or shutil.which("virtctl") is None:
        pytest.skip("Needs kubectl and virtctl")
    try:
        kubectl("get", "datavolume", GOLDEN)
    except subprocess.CalledProcessError:
        pytest.skip(f"Needs a cluster with the {GOLDEN} DataVolume")


@pytest.fixture
def model(volume: KVVolumeModel) -> KVMachineModel:
    model = KVMachineModel().cpu(2).memory(2 * GIGA).volume(volume)
    if not Path("/dev/kvm").exists():
        model.hook(aarch64_without_kvm_script())
    return model


@pytest.fixture
def volume() -> Iterator[KVVolumeModel]:
    model = (
        KVVolumeModel().capacity(9 * GIGA).storage_class(STORAGE_CLASS).clone(GOLDEN)
    )
    with KVVolume(model) as volume:
        volume.wait_until_ready()
        yield model


@pytest.fixture
def network() -> Iterator[KVNetwork]:
    with KVNetwork(KVNetworkModel().ip(HOST_IP)) as network:
        yield network


def test_capabilities(model: KVMachineModel, network: KVNetwork) -> None:
    with KVMachine(model.network(network.model, GUEST_IP)) as machine:
        machine.wait_until_running()
        assert machine.ip == GUEST_IP
        interface = machine.interfaces[0]
        assert [(i.mac, i.ip) for i in network.interfaces] == [
            (interface.mac, GUEST_IP)
        ]
        wait_until_booted(machine, BOOT_TIMEOUT)
        with SSHCommunicator(machine.ip, "root", "a") as ssh:
            assert b"aarch64" in ssh.check("uname -m")
        assert machine.is_powered_on
        machine.type_text("root\n")
        machine.type_text("a\n")
        machine.type_text("echo susa\n")
        machine.press([Key.ENTER])
        screenshot = machine.screenshot()
        assert screenshot.mime_type == "image/png"
        assert "susa" in screenshot.text
        machine.power_off()
        assert not machine.is_powered_on
        machine.power_on()
        assert machine.is_powered_on


def test_sniffer_sees_traffic_between_others(
    model: KVMachineModel, network: KVNetwork
) -> None:
    peer = random_name()
    pod: Manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": peer,
            "annotations": {"k8s.v1.cni.cncf.io/networks": peer},
        },
        "spec": {
            "terminationGracePeriodSeconds": 0,
            "containers": [
                {
                    "name": "c",
                    "image": KVNodePod.IMAGE,
                    "command": ["sleep", "infinity"],
                }
            ],
        },
    }
    create(network.model.attachment(peer, PEER_IP))
    with (
        network.sniffer() as sniffer,
        KVMachine(model.network(network.model, GUEST_IP)) as machine,
    ):
        _ = sniffer.pcap
        machine.wait_until_running()
        create(pod)
        wait_until_booted(machine, BOOT_TIMEOUT)
        with SSHCommunicator(machine.ip, "root", "a") as ssh:
            ssh.check(f"ping -c 3 -W 5 {PEER_IP}")
        kubectl("delete", "pod", peer, "--grace-period=0", "--force")
        kubectl("delete", "network-attachment-definition", peer)
        requests, replies = 0, 0
        while not (requests and replies):
            packet = sniffer.next_packet()
            if ICMP in packet and packet[IP].dst == PEER_IP:
                requests += 1
            if ICMP in packet and packet[IP].src == PEER_IP:
                replies += 1


def test_power(model: KVMachineModel, network: KVNetwork) -> None:
    def boot_id() -> bytes:
        wait_until_booted(machine, BOOT_TIMEOUT)
        with SSHCommunicator(machine.ip, "root", "a") as ssh:
            return ssh.check("cat /proc/sys/kernel/random/boot_id")

    with KVMachine(model.network(network.model, GUEST_IP)) as machine:
        machine.wait_until_running()
        first = boot_id()
        machine.reset()
        second = boot_id()
        assert second != first
        machine.reboot()
        wait_until(lambda: not ping(GUEST_IP, timeout=5), BOOT_TIMEOUT)
        machine.wait_until_running()
        assert boot_id() != second
        machine.shutdown()
        assert not machine.is_powered_on


def test_sniffer_doesnt_leak_when_create_fails() -> None:
    def pods() -> str:
        return kubectl("get", "pods", "-o=name")

    before = pods()
    with pytest.raises(subprocess.CalledProcessError):
        KVSniffer("bridge", timeout=0).create()
    wait_until(lambda: pods() == before, 60)


def test_network_removes_its_bridge() -> None:
    model = KVNetworkModel()
    with KVNetwork(model), KVNodePod() as pod:
        pod.wait_until_ready()
        assert model.get_name() in pod.run("ip", "-o", "link")
    with KVNodePod() as pod:
        pod.wait_until_ready()
        assert model.get_name() not in pod.run("ip", "-o", "link")


CRASH = """
import os, signal
from susa.kubevirt import KVNetwork, KVNetworkModel

network = KVNetwork(KVNetworkModel())
network.create()
print(network.name, flush=True)
os.kill(os.getpid(), signal.SIGKILL)
"""


def test_network_crash() -> None:
    def pods() -> str:
        return kubectl("get", "pods", "-o=name")

    before = pods()
    result = subprocess.run(
        [sys.executable, "-c", CRASH], capture_output=True, text=True, check=False
    )
    assert result.returncode == -signal.SIGKILL, result.stderr
    name = result.stdout.strip()
    attachments = ["get", "network-attachment-definitions", "-o=name"]
    wait_until(lambda: name not in kubectl(*attachments), 120)
    wait_until(lambda: pods() == before, 120)
    with KVNodePod() as pod:
        pod.wait_until_ready()
        assert name not in pod.run("ip", "-o", "link")


def test_network_refuses_an_address_on_the_node() -> None:
    ip = "10.78.0.1"
    with KVNetwork(KVNetworkModel()) as network, KVNodePod() as pod:
        pod.wait_until_ready()
        pod.run("ip", "address", "add", f"{ip}/24", "dev", network.name)
        taken = KVNetwork(KVNetworkModel().ip(ip))
        with pytest.raises(RuntimeError, match=ip):
            taken.create()
        assert taken.name not in pod.run("ip", "-o", "link")


def test_snapshot(model: KVMachineModel, network: KVNetwork) -> None:
    with KVMachine(model.network(network.model, GUEST_IP)) as machine:
        machine.wait_until_running()
        wait_until_booted(machine, BOOT_TIMEOUT)
        with SSHCommunicator(machine.ip, "root", "a") as ssh:
            ssh.check("sync")
        with machine.snapshot() as snapshot:
            with SSHCommunicator(machine.ip, "root", "a") as ssh:
                ssh.check("touch /root/after && sync")
            snapshot.revert()
            assert machine.is_powered_on
            wait_until_booted(machine, BOOT_TIMEOUT)
            with SSHCommunicator(machine.ip, "root", "a") as ssh:
                assert ssh.run("test -e /root/after").returncode != 0
        assert machine.is_powered_on
