# SUSA

SUSA, a recursive acronym for SUSA Unified Systems API, is a Python library for programmatically working with machines.
It's currently in very early development and centered around libvirt machines.

## Usage

A machine, a network, a volume and a communicator are each a resource on its own, and they connect directly. A session
creates resources together, in order, and destroys them in reverse. A communicator keeps trying to connect while its
machine boots:

```python
from susa.communicator.ssh import SSHCommunicator
from susa.core.session import Session
from susa.libvirt import (
    Connection,
    LVMachine,
    LVNetwork,
    LVVolume,
    MachineModel,
    NetworkModel,
    VolumeModel,
)

# A network on a free subnet, and a volume keeping the machine's changes off the image.
network = NetworkModel().default().ip()
volume = VolumeModel().backing("/machines/debian.qcow2")
model = MachineModel().arch("x86_64").efi().default().volume(volume).network(network)

with Connection("qemu:///system"):
    machine = LVMachine(model)
    with (
        Session(network=LVNetwork(network), volume=LVVolume(volume), machine=machine),
        SSHCommunicator(machine.ip, "root", "a") as ssh,
    ):
        print(ssh.check("uname -a"))
```

The same can be a JSON recipe: an array of named objects, each `{"<class>": recipe}` (the builder steps of a model, or
the constructor's arguments of anything else), made when the session's created, in order. They refer to the ones
before with `{"$ref": "<name>"}` (or `"<name>.<attribute>"`), and any argument can also be a recipe itself. Recipes are
pydantic models (`susa.recipes.Recipe`, and `susa.core.session.SessionRecipe` for an array of named ones), and
`python -m susa.recipes` writes their JSON schema (`susa/recipes/recipe.schema.json`, shipped with the package).

```json
[
  {"network_model": {"susa.libvirt.network_model.NetworkModel": ["default", "ip"]}},
  {"volume_model": {"susa.libvirt.volume_model.VolumeModel": [{"backing": "/machines/debian.qcow2"}]}},
  {"machine_model": {"susa.libvirt.machine_model.MachineModel": [
    {"arch": "x86_64"}, "efi", "default", {"volume": {"$ref": "volume_model"}}, {"network": {"$ref": "network_model"}}
  ]}},
  {"network": {"susa.libvirt.network.LVNetwork": {"model": {"$ref": "network_model"}}}},
  {"volume": {"susa.libvirt.volume.LVVolume": {"model": {"$ref": "volume_model"}}}},
  {"machine": {"susa.libvirt.machine.LVMachine": {"model": {"$ref": "machine_model"}}}},
  {"ssh": {"susa.communicator.ssh.SSHCommunicator": {"host": {"$ref": "machine.ip"}, "username": "root", "password": "a"}}}
]
```

The models come first since they refer to each other (e.g. the network reserves the machine's IP), before what they
make is created.

```python
from pathlib import Path

from susa.communicator.ssh import SSHCommunicator
from susa.core.session import Session
from susa.libvirt import Connection

with Connection("qemu:///system"), Session.load(Path("debian.json")) as debian:
    print(debian.get("ssh", SSHCommunicator).check("uname -a"))
```
