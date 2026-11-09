from __future__ import annotations

import contextlib
import logging
import os
import shlex
import subprocess
from collections.abc import Sequence

from susa.core.variable import EnvironmentVariable
from susa.utilities.generic import Guard, guarded, run

LVURI: EnvironmentVariable[str | None] = EnvironmentVariable("SUSA_LVURI", None)


def virsh_command(*args: str) -> list[str]:
    uri = LVURI.get()
    return ["virsh", *(["-c", uri] if uri else []), *args]


def virsh(*args: str, stdin: str | None = None) -> str:
    environment = {**os.environ, "LC_ALL": "C"}
    return run(virsh_command(*args), stdin, environment)


def virsh_data(*args: str, data: bytes = b"") -> bytes:
    command = virsh_command("-q", *args)
    logging.info(shlex.join(command))
    result = subprocess.run(command, input=data, capture_output=True, check=False)
    if result.returncode:
        logging.error(result.stderr.decode())
    result.check_returncode()
    return result.stdout


def virsh_xml(xml: str, *args: str) -> str:
    return virsh(*args, "/dev/stdin", stdin=xml)


def virsh_guarded(
    *commands: Sequence[str],
) -> contextlib.AbstractContextManager[Guard]:
    virshes = (shlex.join(virsh_command(*command)) for command in commands)
    return guarded("; ".join(f"{command} > /dev/null 2>&1" for command in virshes))
