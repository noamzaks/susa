from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile

from susa.core.variable import EnvironmentVariable
from susa.utilities.generic import run

# `None` is libvirt's default, `LIBVIRT_DEFAULT_URI`.
LVURI: EnvironmentVariable[str | None] = EnvironmentVariable("SUSA_LVURI", None)


def virsh_command(*args: str) -> list[str]:
    uri = LVURI.get()
    return ["virsh", *(["-c", uri] if uri else []), *args]


def virsh(*args: str) -> str:
    # Its messages are parsed.
    return run(virsh_command(*args), environment={**os.environ, "LC_ALL": "C"})


# Runs with the data as its input, returning its output as it is (quietly, so it's all there is).
def virsh_data(*args: str, data: bytes = b"") -> bytes:
    command = virsh_command("-q", *args)
    logging.info(shlex.join(command))
    result = subprocess.run(command, input=data, capture_output=True, check=False)
    if result.returncode:
        logging.error(result.stderr.decode())
    result.check_returncode()
    return result.stdout


# Runs with a file of the XML as the last argument.
def virsh_xml(xml: str, *args: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".xml") as file:
        file.write(xml)
        file.flush()
        return virsh(*args, file.name)
