# SUSA

SUSA, a recursive acronym for SUSA Unified Systems API, is a Python library for programmatically working with machines.
It's currently in very early development and centered around libvirt machines.

## Usage

A machine, a network, a volume and a communicator are each a resource on its own, and they connect directly. A
communicator keeps trying to connect while its machine boots:

```python
from susa.communicator.ssh import SSHCommunicator
from susa.libvirt import (
    Connection,
    LVMachine,
    LVNetwork,
    LVVolume,
    MachineModel,
    NetworkModel,
    VolumeModel,
)
from susa.utilities.generic import GIGA
from susa.utilities.networking import SubnetReservation

with Connection("qemu:///system"), SubnetReservation() as subnet:
    # A network on a free subnet, and a volume keeping the machine's changes off the image.
    network_model = NetworkModel().default().ip(subnet.address)
    volume_model = VolumeModel().backing("/machines/debian_x86_64.qcow2")
    machine_model = (
        MachineModel()
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
    {"network_model": {"susa.libvirt.network_model.NetworkModel": ["default", {"ip": {"$ref": "subnet.address"}}]}},
    {"volume_model": {"susa.libvirt.volume_model.VolumeModel": [{"backing": "/machines/debian_x86_64.qcow2"}]}},
    {"machine_model": {"susa.libvirt.machine_model.MachineModel": [
      {"arch": "x86_64"}, "efi", "default", {"memory": 2147483648},
      {"volume": {"$ref": "volume_model"}}, {"network": {"$ref": "network_model"}}
    ]}},
    {"network": {"susa.libvirt.network.LVNetwork": {"model": {"$ref": "network_model"}}}},
    {"volume": {"susa.libvirt.volume.LVVolume": {"model": {"$ref": "volume_model"}}}},
    {"machine": {"susa.libvirt.machine.LVMachine": {"model": {"$ref": "machine_model"}}}},
    {"ssh": {"susa.communicator.ssh.SSHCommunicator": {"host": {"$ref": "machine.ip"}, "username": "root", "password": "a"}}}
  ]
}
```

The models come first since they refer to each other (e.g. the network reserves the machine's IP), before what they
make is created.

```python
from pathlib import Path

from susa.communicator.ssh import SSHCommunicator
from susa.libvirt import Connection
from susa.recipes.session import Session

debian = Session.model_validate_json(Path("debian.json").read_text())
with Connection("qemu:///system"), debian:
    print(debian.get("ssh", SSHCommunicator).check("uname -a"))
```

### In a container

`susa.podman.container.LibvirtContainer` runs libvirt in a rootless podman container (building its image the first
time), whose user and network namespaces the process joins when it's created. Everything else stays as it is, with the
machines' network reachable from the process and what it runs, and connections defaulting to it (through
`LIBVIRT_DEFAULT_URI`). It has to be created while the process has no other threads (e.g. while no `Connection` is
open), and the process stays in its namespaces afterwards (so there can be one per process). Podman keeps working,
through a service the container starts.

```python
from susa.communicator.ssh import SSHCommunicator
from susa.libvirt import Connection
from susa.podman.container import LibvirtContainer

with LibvirtContainer(mounts=["/machines"]), Connection():
    ...  # As above.
```
