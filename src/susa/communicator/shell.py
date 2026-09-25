import re
import shlex
import time
from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import pexpect
from pexpect.spawnbase import SpawnBase
from typing_extensions import override

from susa.core.communicator import AsyncCommandRunner, FileTransferrer, Process
from susa.core.stream import Stream

EXIT = re.compile(rb"SUSA-EXIT-(\d+)\n")
# No line editing (which may reset the terminal's settings), job notifications, echo, output translation (e.g. \n
# to \r\n) or prompts, so the output of commands is exactly what they wrote.
SETUP = b"set +m +o emacs +o vi; stty -echo -opost; PS1=''; PS2=''"
SETUP_TIMEOUT = 60
SETUP_ATTEMPT_TIMEOUT = 10
QUIET_TIME = 1
POLL_INTERVAL = 0.2
UPLOAD_CHUNK_SIZE = 512


class Child(Protocol):
    before: bytes | None
    match: Any

    def expect(self, pattern: Any, timeout: float | None = -1) -> int: ...

    def is_quiet(self, duration: float) -> bool: ...

    def send(self, s: bytes) -> int: ...

    def sendline(self, s: bytes = b"") -> int: ...

    def sendintr(self) -> None: ...

    def close(self) -> None: ...


class QuietSpawn(SpawnBase):  # type: ignore[type-arg]
    def is_quiet(self, duration: float) -> bool:
        """Whether nothing arrives within `duration` seconds (discarding whatever does)."""
        return self.expect([rb"[\s\S]+", pexpect.TIMEOUT], duration) == 1


class Spawn(QuietSpawn, pexpect.spawn):  # type: ignore[type-arg]
    """A `pexpect.spawn` (in bytes mode) that's a `Child`."""


def wait_until_quiet(
    child: Child, quiet_time: float = QUIET_TIME, timeout: float = SETUP_TIMEOUT
) -> None:
    deadline = time.time() + timeout
    while not child.is_quiet(quiet_time):
        if time.time() > deadline:
            raise TimeoutError(f"The connection wasn't quiet for {timeout} seconds")


type Prelude = Callable[[Child], None]


def login(username: str, password: str, quiet_time: float = 3) -> Prelude:
    """Log in (best-effort, whatever the prompts are) by sending a line to get a fresh prompt, the username and the
    password, each once the connection is quiet for `quiet_time` seconds. It should be longer than the login
    program takes to prompt, since input sent before that is usually discarded."""

    def prelude(child: Child) -> None:
        for line in (b"", username.encode(), password.encode()):
            wait_until_quiet(child, quiet_time)
            child.sendline(line)

    return prelude


def escape(data: bytes) -> str:
    """`data` as a `printf` format."""
    return "".join(
        chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}" for b in data
    )


class ShellOutput(Stream):
    def __init__(self, shell: ShellCommunicator, path: str) -> None:
        self.shell = shell
        self.path = path
        self.offset = 0

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.time() + timeout
        head = "" if size is None else f" | head -c {size}"
        while True:
            data, _ = self.shell.execute(
                f"tail -c +{self.offset + 1} {self.path}{head}"
            )
            if data or time.time() >= deadline:
                self.offset += len(data)
                return data
            time.sleep(POLL_INTERVAL)


class ShellProcess(Process):
    def __init__(self, shell: ShellCommunicator, pid: str, directory: str) -> None:
        self.shell = shell
        self.pid = pid
        self.exit_code: int | None = None
        self._stdout = ShellOutput(shell, f"{directory}/out")
        self._stderr = ShellOutput(shell, f"{directory}/err")

    @property
    @override
    def stdout(self) -> Stream:
        return self._stdout

    @property
    @override
    def stderr(self) -> Stream:
        return self._stderr

    @override
    def poll(self) -> int | None:
        if self.exit_code is None and self.shell.execute(f"kill -0 {self.pid}")[1] == 0:
            return None
        return self.wait()

    @override
    def wait(self, timeout: float = 60) -> int:
        # The shell only reports the exit code once.
        if self.exit_code is None:
            self.exit_code = self.shell.execute(f"wait {self.pid}", timeout)[1]
        return self.exit_code

    @override
    def kill(self) -> None:
        self.shell.execute(f"kill {self.pid}")


class ShellCommunicator(AsyncCommandRunner, FileTransferrer):
    """Runs commands in a shell over some connection. `prelude` gets the connection before it's a shell (e.g. to
    log in)."""

    def __init__(self, prelude: Prelude | None = None, quiet_time: float = 3) -> None:
        """Before setting up the shell, wait until the connection is quiet for `quiet_time` seconds. It should be
        long enough for whatever runs at login (which may silently wait for the terminal) to be done."""
        self.prelude = prelude
        self.quiet_time = quiet_time
        self.child: Child | None = None

    @abstractmethod
    def spawn(self) -> Child: ...

    @override
    def create(self) -> None:
        child = self.spawn()
        wait_until_quiet(child, self.quiet_time)
        if self.prelude is not None:
            self.prelude(child)
            wait_until_quiet(child, self.quiet_time)
        deadline = time.time() + SETUP_TIMEOUT
        # Input sent before the shell is ready (e.g. while logging in) may be partly discarded, so retry, clearing
        # the line first (but not before the first attempt, since interrupting a shell that's starting may kill it).
        while True:
            child.sendline(SETUP)
            child.sendline(b"echo SUSA-EXIT-$?")
            try:
                child.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
                break
            except pexpect.TIMEOUT:
                if time.time() > deadline:
                    raise TimeoutError("The shell didn't become ready") from None
                child.sendintr()
        wait_until_quiet(child)
        self.child = child

    @override
    def destroy(self) -> None:
        assert self.child is not None
        self.child.sendline(b"exit")
        self.child.close()
        self.child = None

    def execute(self, command: str, timeout: float = 60) -> tuple[bytes, int]:
        """Run `command` in the shell itself, returning its (combined) output and exit code."""
        assert self.child is not None
        self.child.sendline(command.encode())
        return self.wait_for_exit(timeout, command)

    def wait_for_exit(self, timeout: float, what: str) -> tuple[bytes, int]:
        assert self.child is not None
        self.child.sendline(b"echo SUSA-EXIT-$?")
        try:
            self.child.expect(EXIT, timeout)
        except pexpect.TIMEOUT:
            # Interrupting usually also discards the pending marker line, so send it again.
            self.child.sendintr()
            self.child.sendline(b"echo SUSA-EXIT-$?")
            self.child.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
            wait_until_quiet(self.child)
            raise TimeoutError(f"{what!r} took more than {timeout} seconds") from None
        assert self.child.before is not None
        return self.child.before, int(self.child.match.group(1))

    def checked(self, command: str) -> bytes:
        output, exit_code = self.execute(command)
        if exit_code != 0:
            raise RuntimeError(f"{command!r} failed with {exit_code}: {output!r}")
        return output

    @override
    def start(self, command: str) -> ShellProcess:
        d = shlex.quote(self.checked("mktemp -d").decode().strip())
        output = self.checked(
            f"sh -c {shlex.quote(command)} > {d}/out 2> {d}/err < /dev/null & echo $!"
        )
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return ShellProcess(self, output.split()[-1].decode(), d)

    @override
    def upload(self, local: Path, remote: str) -> None:
        # Only POSIX `printf` (with octal escapes, in lines short enough for the terminal) is assumed.
        target = shlex.quote(remote)
        data = local.read_bytes()
        lines = [f": > {target}"] + [
            f"printf '{escape(data[i : i + UPLOAD_CHUNK_SIZE])}' >> {target}"
            for i in range(0, len(data), UPLOAD_CHUNK_SIZE)
        ]
        self.checked(" &&\n".join(lines))

    @override
    def download(self, remote: str, local: Path) -> None:
        local.write_bytes(self.checked(f"cat {shlex.quote(remote)}"))
