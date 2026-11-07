from __future__ import annotations

import logging
import random
import shlex
import string
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence

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


# Runs a command on this system once it's released, or once this process ends however it does (as the pipe the command
# waits on closes then).
class Guard:
    def __init__(self, command: str) -> None:
        # In a session of its own, so that what stops this process' group (e.g. Ctrl-C) doesn't stop it.
        self.process = subprocess.Popen(
            ["sh", "-c", f"read _; {command}"],
            stdin=subprocess.PIPE,
            start_new_session=True,
        )

    def release(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        self.process.wait()


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
