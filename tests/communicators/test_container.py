from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator, Iterator

import pytest

from susa.communicators.container import ContainerCommunicator

NET = os.readlink("/proc/self/ns/net").encode()


# The init of user, network and PID namespaces of its own, like a rootless container's.
@contextlib.contextmanager
def container() -> Generator[int, None, None]:
    process = subprocess.Popen(
        ["unshare", "--user", "--net", "--pid", "--fork", "sleep", "infinity"]
    )
    # Until `unshare` forked the init, which replaced itself with `sleep`.
    time.sleep(0.5)
    init = subprocess.run(
        ["pgrep", "-P", str(process.pid)], check=True, capture_output=True
    )
    yield int(init.stdout)
    process.kill()
    process.wait()


@pytest.fixture(scope="module")
def target() -> Iterator[int]:
    with container() as init:
        yield init


def sleeping(seconds: int) -> bool:
    time.sleep(0.5)
    command = ["pgrep", "-fx", f"sleep {seconds}"]
    return subprocess.run(command, check=False).returncode == 0


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
    assert not sleeping(3603)


# They're in its PID namespace, so they stop with its init.
def test_stop() -> None:
    with container() as init:
        command = ContainerCommunicator(init).start("sleep 3604; true")
        assert sleeping(3604)
        os.kill(init, signal.SIGKILL)
        assert not sleeping(3604)
        assert command.wait(timeout=10) != 0


# They stop when this process ends, even when it's killed.
def test_crash(target: int) -> None:
    code = f"""
import os, signal, time
from susa.communicators.container import ContainerCommunicator
ContainerCommunicator({target}).start("sleep 3609; true")
time.sleep(0.5)
os.kill(os.getpid(), signal.SIGKILL)
"""
    subprocess.run([sys.executable, "-c", code], check=False)
    assert not sleeping(3609)
