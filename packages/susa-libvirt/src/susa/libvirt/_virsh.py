from __future__ import annotations

import os
import tempfile

from susa.core.variable import Variable
from susa.utilities.generic import run

# `None` is libvirt's default, `LIBVIRT_DEFAULT_URI`.
URI: Variable[str | None] = Variable(None)


def virsh_command(*args: str) -> list[str]:
    uri = URI.get()
    return ["virsh", *(["-c", uri] if uri else []), *args]


def virsh(*args: str) -> str:
    # Its messages are parsed.
    return run(virsh_command(*args), environment={**os.environ, "LC_ALL": "C"})


# Runs with a file of the XML as the last argument.
def virsh_xml(xml: str, *args: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".xml") as file:
        file.write(xml)
        file.flush()
        return virsh(*args, file.name)
