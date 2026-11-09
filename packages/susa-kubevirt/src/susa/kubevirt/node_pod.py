from __future__ import annotations

import json

from typing_extensions import override

from susa.core.resource import Resource
from susa.kubevirt._kubectl import (
    create,
    deletion,
    kubectl,
    kubectl_guarded,
    random_name,
    wait,
)


class KVNodePod(Resource):
    IMAGE = "docker.io/nicolaka/netshoot:v0.15"

    def __init__(self, timeout: float = 300) -> None:
        self.timeout = timeout
        self.name = random_name()

    @override
    def create(self) -> None:
        delete = [*deletion("pod", self.name), "--grace-period=0", "--force"]
        with kubectl_guarded(delete) as self.guard:
            create(KVNodePod.manifest(self.name, ["sleep", "infinity"]))

    @override
    def destroy(self) -> None:
        kubectl("delete", "pod", self.name, "--grace-period=0", "--force")
        self.guard.cancel()

    def wait_until_ready(self) -> None:
        wait("pod", self.name, "condition=Ready", self.timeout)

    def run(self, *command: str) -> str:
        return kubectl("exec", self.name, "--", *command)

    @staticmethod
    def manifest(name: str, command: list[str]) -> dict[str, object]:
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name},
            "spec": {
                "hostNetwork": True,
                "restartPolicy": "Never",
                "terminationGracePeriodSeconds": 0,
                "containers": [
                    {
                        "name": name,
                        "image": KVNodePod.IMAGE,
                        "command": command,
                        "securityContext": {
                            "capabilities": {"add": ["NET_ADMIN", "NET_RAW"]}
                        },
                    }
                ],
            },
        }

    @staticmethod
    def run_command(command: list[str]) -> list[str]:
        name = random_name()
        overrides = f"--overrides={json.dumps(KVNodePod.manifest(name, command))}"
        image = f"--image={KVNodePod.IMAGE}"
        return ["run", name, "--rm", "-i", "--restart=Never", image, overrides]
