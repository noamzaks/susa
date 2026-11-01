from __future__ import annotations

from typing_extensions import override

from susa.core.resource import Resource
from susa.kubevirt._kubectl import create, kubectl, random_name, wait


# A pod in a node's network namespace, for what's only there (e.g. bridges). With several nodes, it's on any of them.
class KVNodePod(Resource):
    IMAGE = "docker.io/nicolaka/netshoot:v0.15"

    def __init__(self, timeout: float = 300) -> None:
        self.timeout = timeout
        self.name = random_name()

    @override
    def create(self) -> None:
        create(
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": self.name},
                "spec": {
                    "hostNetwork": True,
                    "restartPolicy": "Never",
                    "terminationGracePeriodSeconds": 0,
                    "containers": [
                        {
                            "name": "node",
                            "image": KVNodePod.IMAGE,
                            "command": ["sleep", "infinity"],
                            "securityContext": {
                                "capabilities": {"add": ["NET_ADMIN", "NET_RAW"]}
                            },
                        }
                    ],
                },
            }
        )

    @override
    def destroy(self) -> None:
        kubectl("delete", "pod", self.name, "--grace-period=0", "--force")

    def wait_until_ready(self) -> None:
        wait("pod", self.name, "condition=Ready", self.timeout)

    def run(self, *command: str) -> str:
        return kubectl("exec", self.name, "--", *command)
