# SUSA

SUSA, a recursive acronym for SUSA Unified Systems API, is a Python library for programmatically working with machines.
It's currently in very early development and centered around libvirt machines.

## Usage

A machine, a network, a volume and a communicator are each a resource on its own, and they connect directly. A session
creates resources together, in order, and destroys them in reverse:

```python
from susa.communicator.ssh import SSHCommunicator
from susa.core.machine import wait_until_booted
from susa.libvirt import (
    Connection,
    LVMachine,
    LVNetwork,
    LVVolume,
    MachineModel,
    NetworkModel,
    VolumeModel,
)
from susa.session import Session

# A network on a free subnet (which other processes won't take), and a volume keeping the machine's changes off the image.
network = NetworkModel().default().ip()
volume = VolumeModel().backing("/machines/debian.qcow2")
model = MachineModel().arch("x86_64").efi().default().volume(volume).network(network)

with Connection("qemu:///system"):
    machine = LVMachine(model)
    with Session(network=LVNetwork(network), volume=LVVolume(volume), machine=machine):
        wait_until_booted(machine)
        with SSHCommunicator(machine, "root", "a") as ssh:
            print(ssh.check("uname -a"))
```

The same can be a JSON recipe: an array of named resources, made in order, each `{"<class>": recipe}` (the builder
steps of a model, or the constructor's arguments of anything else), referring to the ones before it with
`{"$ref": "<name>"}` (or `"<name>.<attribute>"`). `susa/recipes/recipe.schema.json` has the schema of them all.

```json
[
  {"network": {"susa.libvirt.network.LVNetwork": {"model": ["default", "ip"]}}},
  {"volume": {"susa.libvirt.volume.LVVolume": {"model": [{"backing": "/machines/debian.qcow2"}]}}},
  {"machine": {"susa.libvirt.machine.LVMachine": {"model": [
    {"arch": "x86_64"}, "efi", "default", {"volume": {"$ref": "volume.model"}}, {"network": {"$ref": "network.model"}}
  ]}}}
]
```

`Session.parse` makes a session of such a recipe, and `add` makes another object in it from a recipe, referring to the
objects already there:

```python
from pathlib import Path

from susa.core.machine import wait_until_booted
from susa.libvirt import Connection, LVMachine
from susa.session import Session

ssh = {
    "susa.communicator.ssh.SSHCommunicator": {
        "machine": {"$ref": "machine"},
        "username": "root",
        "password": "a",
    }
}
with Connection("qemu:///system"), Session.parse(Path("debian.json")) as debian:
    wait_until_booted(debian.get("machine", LVMachine))
    with debian.add("ssh", ssh) as c:
        print(c.check("uname -a"))
```
