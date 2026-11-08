from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from susa.utilities.generic import Deadline, Guard, guarded, memory_file, wait_until


def test_deadline_test() -> None:
    Deadline(None).test("Not reached")
    Deadline(60).test("Not reached")
    with pytest.raises(TimeoutError, match="^It didn't happen within 0 seconds$"):
        Deadline(0).test("It didn't happen")


def test_guard(tmp_path: Path) -> None:
    ran = tmp_path / "ran"
    Guard(f"touch {ran}").cancel()
    assert not ran.exists()
    Guard(f"touch {ran}").release()
    assert ran.exists()
    ran.unlink()
    with guarded(f"touch {ran}") as guard:
        guard.cancel()
    assert not ran.exists()
    with pytest.raises(ValueError), guarded(f"touch {ran}"):
        raise ValueError
    assert ran.exists()


def kill_tree(pid: int) -> None:
    output = subprocess.check_output(["ps", "-A", "-o", "pid=", "-o", "ppid="])
    parents: dict[int, int] = {}
    for line in output.decode().splitlines():
        child, parent = line.split()
        parents[int(child)] = int(parent)
    tree = {pid}
    while grown := {p for p, parent in parents.items() if parent in tree} - tree:
        tree |= grown
    for process in tree:
        os.kill(process, signal.SIGKILL)


def test_guard_crash(tmp_path: Path) -> None:
    ran = tmp_path / "ran"
    code = f"""
import time
from susa.utilities.generic import Guard
guard = Guard("touch {ran}")
print(flush=True)
time.sleep(3600)
"""
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    assert process.stdout is not None
    process.stdout.readline()
    kill_tree(process.pid)
    process.wait()
    wait_until(ran.exists, 10)


def test_memory_file() -> None:
    with memory_file(b"a") as path:
        subprocess.run(["sh", "-c", f"cat {path}; printf b >> {path}"], check=True)
        assert path.read_bytes() == b"ab"
    assert not path.exists()
