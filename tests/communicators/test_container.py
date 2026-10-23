from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator

import pytest

from susa.communicators.container import ContainerCommunicator

NET = os.readlink("/proc/self/ns/net").encode()


# A process in user and network namespaces of its own, like a rootless container's.
@pytest.fixture(scope="module")
def target() -> Iterator[int]:
    process = subprocess.Popen(["unshare", "--user", "--net", "sleep", "infinity"])
    # Until `unshare` replaced itself with `sleep`, in the namespaces.
    time.sleep(0.5)
    yield process.pid
    process.kill()
    process.wait()


def test_run(target: int) -> None:
    result = ContainerCommunicator(target).run("readlink /proc/self/ns/net; exit 3")
    assert result.returncode == 3
    assert result.stdout.strip() not in (b"", NET)


def test_namespaces(target: int) -> None:
    container = ContainerCommunicator(target, ["user"])
    assert container.check("readlink /proc/self/ns/net").strip() == NET


def test_start(target: int) -> None:
    command = ContainerCommunicator(target).start("cat")
    command.stdin.write(b"a\x00\xff\n")
    command.stdin.close()
    assert command.wait(timeout=10) == 0
    assert command.stdout.read_all(timeout=10) == b"a\x00\xff\n"


# They're this process' children, so they stop.
def test_kill(target: int) -> None:
    command = ContainerCommunicator(target).start("exec sleep 3603")
    command.kill()
    assert command.wait(timeout=10) == -9
    time.sleep(0.5)
    sleeping = subprocess.run(["pgrep", "-f", "^sleep 3603$"], check=False)
    assert sleeping.returncode == 1
