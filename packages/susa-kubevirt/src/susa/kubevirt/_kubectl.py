from __future__ import annotations

import contextlib
import json
import shlex
from collections.abc import Sequence
from typing import Any, TypeAlias

from susa.utilities.generic import Guard, guarded, random_id, run

Manifest: TypeAlias = dict[str, Any]


def kubectl(*args: str, stdin: str | None = None) -> str:
    return run(["kubectl", *args], stdin)


def virtctl(*args: str) -> str:
    return run(["virtctl", *args])


def create(manifest: Manifest) -> None:
    kubectl("create", "-f", "-", stdin=json.dumps(manifest))


def delete(resource: str, name: str, timeout: float) -> None:
    kubectl("delete", resource, name, f"--timeout={timeout}s")


def wait(resource: str, name: str, condition: str, timeout: float) -> None:
    kubectl("wait", f"{resource}/{name}", f"--for={condition}", f"--timeout={timeout}s")


def kubectl_guarded(
    *commands: Sequence[str],
) -> contextlib.AbstractContextManager[Guard]:
    kubectls = (shlex.join(["kubectl", *command]) for command in commands)
    return guarded("; ".join(f"{command} > /dev/null 2>&1" for command in kubectls))


def deletion(resource: str, name: str) -> list[str]:
    return ["delete", resource, name, "--ignore-not-found"]


def random_name() -> str:
    return f"susa-{random_id(10).lower()}"
