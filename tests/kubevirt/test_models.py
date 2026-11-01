from __future__ import annotations

import json

from susa.kubevirt import KVMachineModel, KVNetworkModel, KVVolumeModel
from susa.utilities.generic import GIGA


def test_volume() -> None:
    assert KVVolumeModel("v").capacity(GIGA).clone("golden").manifest["spec"] == {
        "source": {"pvc": {"name": "golden", "namespace": "default"}},
        "storage": {
            "resources": {"requests": {"storage": str(GIGA)}},
        },
    }


def test_blank_volume() -> None:
    assert KVVolumeModel("v").manifest["spec"] == {
        "source": {"blank": {}},
        "storage": {},
    }


def test_network_without_ip_has_no_addresses() -> None:
    config: dict[str, object] = {
        "cniVersion": "0.3.1",
        "name": "n",
        "type": "bridge",
        "bridge": "n",
        "isGateway": False,
        "ipam": {},
    }
    assert KVNetworkModel("n").manifest["spec"] == {"config": json.dumps(config)}


def test_machine() -> None:
    network = KVNetworkModel("n").ip("10.77.0.1", 16)
    model = (
        KVMachineModel("m")
        .cpu(2)
        .memory(GIGA)
        .volume(KVVolumeModel("v"))
        .network(network, "10.77.0.5")
        .network(KVNetworkModel("o"))
    )
    assert model.manifest["spec"] == {
        "runStrategy": "Always",
        "template": {
            "metadata": {"annotations": {}},
            "spec": {
                "domain": {
                    "cpu": {"cores": 2},
                    "memory": {"guest": str(GIGA)},
                    "devices": {
                        "disks": [{"name": "disk0", "disk": {"bus": "virtio"}}],
                        "interfaces": [
                            {"name": "net0", "bridge": {}},
                            {"name": "net1", "bridge": {}},
                        ],
                    },
                },
                "networks": [
                    {"name": "net0", "multus": {"networkName": "m-net0"}},
                    {"name": "net1", "multus": {"networkName": "o"}},
                ],
                "volumes": [{"name": "disk0", "dataVolume": {"name": "v"}}],
            },
        },
    }
    assert model.get_ips() == {"net0": "10.77.0.5", "net1": None}
    assert model.get_attachments() == {
        "m-net0": network.attachment("m-net0", "10.77.0.5")
    }


def test_attachment() -> None:
    config = {
        "cniVersion": "0.3.1",
        "name": "a",
        "type": "bridge",
        "bridge": "n",
        "isGateway": True,
        "ipam": {
            "type": "static",
            "addresses": [{"address": "10.77.0.5/16", "gateway": "10.77.0.1"}],
        },
    }
    network = KVNetworkModel("n").ip("10.77.0.1", 16)
    assert network.attachment("a", "10.77.0.5")["spec"] == {
        "config": json.dumps(config)
    }


def test_manifest_is_editable() -> None:
    model = KVMachineModel("m").interface("mine", {"pod": {}})
    model.manifest["spec"]["runStrategy"] = "Manual"
    assert model.manifest["spec"]["runStrategy"] == "Manual"
    spec = model.manifest["spec"]["template"]["spec"]
    assert spec["networks"] == [{"name": "mine", "pod": {}}]
    model.network(KVNetworkModel("n"))
    assert spec["networks"][1]["name"] == "net1"


def test_network_rename() -> None:
    network = KVNetworkModel("a").name("b")
    assert network.get_name() == "b"
    config = json.loads(network.manifest["spec"]["config"])
    assert (config["name"], config["bridge"]) == ("b", "b")


def test_emulate_adds_a_hook() -> None:
    model = KVMachineModel("m").emulate("ppc64le")
    assert 'machine="pseries"' in model.get_hooks()["m-hook0"]
    annotations = model.manifest["spec"]["template"]["metadata"]["annotations"]
    sidecars = json.loads(annotations["hooks.kubevirt.io/hookSidecars"])
    assert sidecars[0]["configMap"]["name"] == "m-hook0"


def test_interface_placement() -> None:
    model = KVMachineModel("m").network(
        KVNetworkModel("n"), None, "e1000", "0000:00:0b.0"
    )
    interface = model.manifest["spec"]["template"]["spec"]["domain"]["devices"][
        "interfaces"
    ][0]
    assert interface == {
        "name": "net0",
        "bridge": {},
        "model": "e1000",
        "pciAddress": "0000:00:0b.0",
    }


def test_kernel() -> None:
    model = KVMachineModel("m").kernel("image", "/kernel", "/initrd", "console=ttyS0")
    firmware = model.manifest["spec"]["template"]["spec"]["domain"]["firmware"]
    assert firmware == {
        "kernelBoot": {
            "container": {
                "image": "image",
                "kernelPath": "/kernel",
                "initrdPath": "/initrd",
            },
            "kernelArgs": "console=ttyS0",
        }
    }
