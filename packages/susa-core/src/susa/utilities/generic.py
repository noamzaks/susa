from __future__ import annotations

import contextlib
import logging
import os
import random
import shlex
import string
import subprocess
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from pathlib import Path

GIGA = 1 << 30


def random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


class Deadline:
    def __init__(self, timeout: float | None) -> None:
        self.timeout = timeout
        self.end = None if timeout is None else time.monotonic() + timeout

    def remaining(self) -> float | None:
        return None if self.end is None else max(0.0, self.end - time.monotonic())

    def passed(self) -> bool:
        return self.remaining() == 0

    def test(self, message: str) -> None:
        if self.passed():
            raise TimeoutError(f"{message} within {self.timeout} seconds")


def wait_until(
    test: Callable[[], bool],
    timeout: float | None = None,
    interval: float = 0.1,
) -> None:
    deadline = Deadline(timeout)
    while True:
        deadline.test("The condition didn't hold")
        if test():
            return
        time.sleep(interval)


class Guard:
    def __init__(self, command: str) -> None:
        script = f"read _ || {{ {command}\n}} > /dev/null"
        self.process = subprocess.Popen(
            ["sh", "-c", f"exec 3<&0; sh -c {shlex.quote(script)} <&3 3<&- &"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        self.process.wait()

    def release(self) -> None:
        self._close(b"")

    def cancel(self) -> None:
        self._close(b"\n")

    def _close(self, data: bytes) -> None:
        assert self.process.stdin is not None and self.process.stdout is not None
        if not self.process.stdin.closed:
            self.process.stdin.write(data)
            self.process.stdin.close()
        self.process.stdout.read()


@contextlib.contextmanager
def guarded(command: str) -> Generator[Guard, None, None]:
    guard = Guard(command)
    try:
        yield guard
    except BaseException:
        guard.release()
        raise


@contextlib.contextmanager
def memory_file(data: bytes = b"") -> Generator[Path, None, None]:
    fd = os.memfd_create("susa")
    try:
        path = Path(f"/proc/{os.getpid()}/fd/{fd}")
        path.write_bytes(data)
        yield path
    finally:
        os.close(fd)


def run(
    command: Sequence[str],
    stdin: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    logging.info(shlex.join(command))
    result = subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    if result.returncode:
        logging.error(result.stderr)
    result.check_returncode()
    return result.stdout
