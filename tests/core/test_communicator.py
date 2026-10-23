from __future__ import annotations

import pytest

from susa.core.communicator import HostAsyncCommandRunner

HOST = HostAsyncCommandRunner()


def test_run() -> None:
    result = HOST.run("echo out; echo err >&2; exit 3")
    assert (result.returncode, result.stdout, result.stderr) == (3, b"out\n", b"err\n")
    # More than fits in pipes, of both.
    result = HOST.run("head -c 1000000 /dev/zero >&2; head -c 1000000 /dev/zero")
    assert (len(result.stdout), len(result.stderr)) == (1000000, 1000000)
    with pytest.raises(TimeoutError):
        HOST.run("sleep 5", timeout=0.2)


def test_start() -> None:
    command = HOST.start("cat; echo done >&2")
    assert command.poll() is None
    command.stdin.write(b"a\x00\xff\n")
    assert command.stdout.read_until(b"\n", timeout=5) == b"a\x00\xff\n"
    command.stdin.close()
    assert command.wait(timeout=5) == 0
    assert command.stderr.read_all(timeout=5) == b"done\n"
    with pytest.raises(EOFError):
        command.stdout.read()


def test_start_kill() -> None:
    command = HOST.start("exec sleep 3600")
    with pytest.raises(TimeoutError):
        command.wait(timeout=0.2)
    command.kill()
    assert command.wait(timeout=5) == -9
