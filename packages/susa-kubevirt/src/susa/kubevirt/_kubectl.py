from __future__ import annotations

import json
from typing import Any, TypeAlias

from susa.utilities.generic import random_id, run

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


# Kubernetes' names are lowercase.
def random_name() -> str:
    return f"susa-{random_id(10).lower()}"
