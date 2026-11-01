# SUSA

SUSA, a recursive acronym for SUSA Unified Systems API, is a Python library for programmatically working with machines.
It's currently in very early development and centered around libvirt machines.

## Usage

A machine, a network, a volume and a communicator are each a resource on its own, and they connect directly. A
communicator keeps trying to connect while its machine boots:

```python
from susa.communicators.ssh import SSHCommunicator
from susa.libvirt import (
    URI,
    LVMachine,
    LVNetwork,
    LVVolume,
    LVMachineModel,
    LVNetworkModel,
    LVVolumeModel,
)
from susa.utilities.generic import GIGA
from susa.utilities.networking import SubnetReservation

with URI.set("qemu:///system"), SubnetReservation() as subnet:
    # A network on a free subnet, and a volume keeping the machine's changes off the image.
    network_model = LVNetworkModel().default().ip(subnet.ip)
    volume_model = LVVolumeModel().backing("/machines/debian_x86_64.qcow2")
    machine_model = (
        LVMachineModel()
        .arch("x86_64")
        .efi()
        .default()
        .memory(2 * GIGA)
        .volume(volume_model)
        .network(network_model)
    )

    with (
        LVNetwork(network_model),
        LVVolume(volume_model),
        LVMachine(machine_model) as machine,
        SSHCommunicator(machine.ip, "root", "a") as ssh,
    ):
        print(ssh.check("uname -a"))
```

The same can be a session: an array of named recipes in `objects`, each `{"<class>": recipe}` (the builder steps of a
model, or the constructor's arguments of anything else), made and created in order, and destroyed in reverse. They refer
to the ones before with `{"$ref": "<name>"}` (or `"<name>.<attribute>"`), and any argument can also be a recipe itself.
Recipes and sessions are pydantic models (`susa.recipes.Recipe`, `susa.recipes.session.Session`), and `python -m
susa.recipes` writes their JSON schema (`susa/recipes/recipe.schema.json`, shipped with the package), which `$schema`
can point at.

```json
{
  "$schema": "recipe.schema.json",
  "objects": [
    {"subnet": {"susa.utilities.networking.SubnetReservation": {}}},
    {"network_model": {"susa.libvirt.network_model.LVNetworkModel": ["default", {"ip": {"$ref": "subnet.ip"}}]}},
    {"volume_model": {"susa.libvirt.volume_model.LVVolumeModel": [{"backing": "/machines/debian_x86_64.qcow2"}]}},
    {"machine_model": {"susa.libvirt.machine_model.LVMachineModel": [
      {"arch": "x86_64"}, "efi", "default", {"memory": 2147483648},
      {"volume": {"$ref": "volume_model"}}, {"network": {"$ref": "network_model"}}
    ]}},
    {"network": {"susa.libvirt.network.LVNetwork": {"model": {"$ref": "network_model"}}}},
    {"volume": {"susa.libvirt.volume.LVVolume": {"model": {"$ref": "volume_model"}}}},
    {"machine": {"susa.libvirt.machine.LVMachine": {"model": {"$ref": "machine_model"}}}},
    {"ssh": {"susa.communicators.ssh.SSHCommunicator": {"ip": {"$ref": "machine.ip"}, "username": "root", "password": "a"}}}
  ]
}
```

The models come first since they refer to each other (e.g. the network reserves the machine's IP), before what they
make is created.

```python
from pathlib import Path

from susa.communicators.ssh import SSHCommunicator
from susa.libvirt import URI
from susa.recipes.session import Session

debian = Session.model_validate_json(Path("debian.json").read_text())
with URI.set("qemu:///system"), debian:
    print(debian.get("ssh", SSHCommunicator).check("uname -a"))
```

### In a container

Commands that run on the host (e.g. the ssh, telnet and rlogin clients, `ping`, sniffers' `tcpdump` and subnet
reservations' `ip route`) run through `susa.core.communicator.HOST`, a `Variable` holding an `AsyncCommandRunner`.
Objects take its value when they're made, and `with HOST.set(...):` changes it for a block.

Consoles run on a terminal from `script` (`util-linux-script` on Fedora).

`susa.podman.container.LibvirtContainer` runs libvirt in a rootless podman container (of the `susa-libvirt` image, built
the first time). Until it's destroyed, virsh defaults to it, and the host is a
`susa.communicators.container.ContainerCommunicator`, which runs commands (with this system's programs) in the
container's user and network namespaces, where they reach its machines. It also sets `LIBVIRT_DEFAULT_URI`,
`SUSA_SUBNETS_LOCK` and `SUSA_SESSION` (a session recipe whose `host` is the host), so processes started meanwhile (e.g.
other Python programs using SUSA, with `susa-recipes`) default to it too:

```python
from susa.libvirt import URI
from susa.podman.container import LibvirtContainer

with LibvirtContainer(mounts=["/machines"]):
    ...  # As above.
```

`susa.kubevirt` runs machines on a single-node Kubernetes cluster (bridges are per node) with KubeVirt, using the current
kubeconfig. It needs KubeVirt, CDI
(for volumes), Multus (for networks), `kubectl` and `virtctl`, and for snapshots a CSI driver that supports them and KubeVirt's `Snapshot` feature
gate. A storage class needs a CDI StorageProfile with its access and volume modes. Machines are on bridges: `KVMachineModel.network(network, ip)` gives the guest that IP over DHCP, and
`KVNetworkModel.ip` is the node's address there, through which it reaches them. Bridged traffic goes through the node's
firewall, so with firewalld, trust SUSA's bridges once (`sudo firewall-cmd --permanent --zone=trusted
--add-interface=susa+` and `--reload`), which covers the default names of networks. Snapshots are of the disks: KubeVirt
doesn't save memory, so reverting boots the machine again.

Machines of other architectures than the node's need a virt-launcher image with their QEMU, which
`scripts/kubevirt-launcher/setup.sh` builds and installs on a single-node Arm64 cluster (it enables an alpha feature gate
and replaces the image KubeVirt uses, and the local registry it makes loses the image when its pod goes away).
`KVMachineModel.cross_architecture("amd64")` is KubeVirt's own way, for x86_64 on Arm64, without video.
`KVMachineModel.emulate(arch)` is for `i686`, `ppc64le`, `riscv64`, `armv7l` and `mips`. A kernel outside the disk comes from
a container image (`KVMachineModel.kernel`). Guests run through software emulation, so they're slow.

```python
from susa.communicators.ssh import SSHCommunicator
from susa.kubevirt import (
    KVMachine,
    KVMachineModel,
    KVNetwork,
    KVNetworkModel,
    KVVolume,
    KVVolumeModel,
)
from susa.utilities.generic import GIGA

network_model = KVNetworkModel().ip("10.77.0.1")
volume_model = KVVolumeModel().capacity(12 * GIGA).clone("debian")
machine_model = (
    KVMachineModel()
    .memory(2 * GIGA)
    .volume(volume_model)
    .network(network_model, "10.77.0.5")
)

with (
    KVNetwork(network_model) as network,
    network.sniffer() as sniffer,
    KVVolume(volume_model),
    KVMachine(machine_model) as machine,
    SSHCommunicator(machine.ip, "root", "a") as ssh,
):
    print(ssh.check("uname -a"))
```
