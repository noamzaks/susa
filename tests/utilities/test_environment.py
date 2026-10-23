from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

CONTAINER = "susa.communicators.container.ContainerCommunicator"
MACHINE_MODEL = "susa.libvirt.machine_model.MachineModel"


def python(
    code: str, session: dict[str, Any] | str
) -> subprocess.CompletedProcess[str]:
    recipe = session if isinstance(session, str) else json.dumps(session)
    environment = {**os.environ, "SUSA_SESSION": recipe}
    command = [sys.executable, "-c", code]
    return subprocess.run(
        command, env=environment, capture_output=True, text=True, check=False
    )


def test_host() -> None:
    host = {CONTAINER: {"pid": 1, "namespaces": ["net"]}}
    code = "from susa.core.communicator import HOST; print(vars(HOST.get()))"
    result = python(code, {"objects": [{"host": host}]})
    assert result.stdout == "{'pid': 1, 'namespaces': ['net']}\n"


def test_host_class() -> None:
    code = "from susa.core.communicator import HOST; HOST.get()"
    result = python(code, {"objects": [{"host": {MACHINE_MODEL: []}}]})
    assert (
        "TypeError: SUSA_SESSION's 'host' isn't a AsyncCommandRunner" in result.stderr
    )


# Only once it's needed.
def test_lazy() -> None:
    code = "from susa.core.communicator import HOST; print('imported'); HOST.get()"
    result = python(code, "not a recipe")
    assert result.stdout == "imported\n"
    assert "ValidationError" in result.stderr


def test_without_host() -> None:
    code = "from susa.core.communicator import HOST; print(type(HOST.get()).__name__)"
    result = python(code, {"objects": [{"model": {MACHINE_MODEL: []}}]})
    assert result.stdout == "HostAsyncCommandRunner\n"
