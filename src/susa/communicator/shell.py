from __future__ import annotations

import re
import shlex
import time
from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import TypeAlias

import pexpect
from typing_extensions import override

from susa.communicator.terminal import Terminal
from susa.core.communicator import AsyncCommand, AsyncCommandRunner, FileTransferrer
from susa.core.stream import OutputStream

EXIT = re.compile(rb"SUSA-EXIT-(\d+)\n")
MARK_EXIT = b"echo SUSA-EXIT-$?"
# No line editing (which may reset the terminal's settings), job notifications, echo, output translation (e.g. \n
# to \r\n) or prompts, so the output of commands is exactly what they wrote.
SETUP = b"set +m +o emacs +o vi; stty -echo -opost; PS1=''; PS2=''"
SETUP_TIMEOUT = 60
SETUP_ATTEMPT_TIMEOUT = 10
RECOVERY_QUIET_TIME = 1
POLL_INTERVAL = 0.2
UPLOAD_CHUNK_SIZE = 512

Prelude: TypeAlias = Callable[[Terminal], None]


def login(username: str, password: str, quiet_time: float = 3) -> Prelude:
    """Log in (best-effort, whatever the prompts are) by sending a line to get a fresh prompt, the username and the
    password, each once the terminal is quiet for `quiet_time` seconds. It should be longer than the login program
    takes to prompt, since input sent before that is usually discarded."""

    def prelude(terminal: Terminal) -> None:
        for line in (b"", username.encode(), password.encode()):
            terminal.wait_until_quiet(quiet_time, SETUP_TIMEOUT)
            terminal.sendline(line)

    return prelude


def printf_format(data: bytes) -> str:
    """A (single-quotable) `printf` format that prints `data`."""
    return "".join(
        chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}" for b in data
    )


class ShellOutputStream(OutputStream):
    """A file being written by a `ShellCommand`, read (from where the last read stopped) through the shell."""

    def __init__(self, shell: ShellCommunicator, path: str) -> None:
        self.shell = shell
        self.path = path
        self.offset = 0

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.time() + timeout
        head = "" if size is None else f" | head -c {size}"
        while True:
            data = self.shell.execute(
                f"tail -c +{self.offset + 1} {self.path}{head}"
            ).stdout
            if data or time.time() >= deadline:
                self.offset += len(data)
                return data
            time.sleep(POLL_INTERVAL)


class ShellCommand(AsyncCommand):
    """A background job of a `ShellCommunicator`'s shell, with its outputs in files in `directory`."""

    def __init__(self, shell: ShellCommunicator, pid: str, directory: str) -> None:
        self.shell = shell
        self.pid = pid
        self.exit_code: int | None = None
        self._stdout = ShellOutputStream(shell, f"{directory}/out")
        self._stderr = ShellOutputStream(shell, f"{directory}/err")

    @property
    @override
    def stdout(self) -> OutputStream:
        return self._stdout

    @property
    @override
    def stderr(self) -> OutputStream:
        return self._stderr

    @override
    def poll(self) -> int | None:
        if (
            self.exit_code is None
            and self.shell.execute(f"kill -0 {self.pid}").returncode == 0
        ):
            return None
        return self.wait()

    @override
    def wait(self, timeout: float = 60) -> int:
        # The shell only reports the exit code once.
        if self.exit_code is None:
            self.exit_code = self.shell.execute(f"wait {self.pid}", timeout).returncode
        return self.exit_code

    @override
    def kill(self) -> None:
        self.shell.execute(f"kill {self.pid}")


class ShellCommunicator(AsyncCommandRunner, FileTransferrer):
    """Runs commands in a POSIX shell over a `Terminal`, assuming little more than POSIX `sh`, `stty` and `mktemp`.

    `prelude` gets the terminal before it's a shell (e.g. to log in). Setting the shell up waits until the terminal
    is quiet for `quiet_time` seconds, which should be long enough for whatever runs at login (which may silently
    wait for the terminal) to be done."""

    def __init__(self, prelude: Prelude | None = None, quiet_time: float = 3) -> None:
        self.prelude = prelude
        self.quiet_time = quiet_time
        self.terminal: Terminal | None = None

    @abstractmethod
    def open_terminal(self) -> Terminal: ...

    @override
    def create(self) -> None:
        terminal = self.open_terminal()
        terminal.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
        if self.prelude is not None:
            self.prelude(terminal)
            terminal.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
        deadline = time.time() + SETUP_TIMEOUT
        # Input sent before the shell is ready (e.g. while logging in) may be partly discarded, so retry, clearing
        # the line first (but not before the first attempt, since interrupting a shell that's starting may kill it).
        while True:
            terminal.sendline(SETUP)
            terminal.sendline(MARK_EXIT)
            try:
                terminal.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
                break
            except pexpect.TIMEOUT:
                if time.time() > deadline:
                    raise TimeoutError("The shell didn't become ready") from None
                terminal.sendintr()
        terminal.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
        self.terminal = terminal

    @override
    def destroy(self) -> None:
        assert self.terminal is not None
        self.terminal.sendline(b"exit")
        self.terminal.close()
        self.terminal = None

    def execute(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]:
        """Run `command` in the shell itself (so e.g. `cd` affects later commands). Its stdout and stderr are both
        in the result's `stdout`."""
        assert self.terminal is not None
        self.terminal.sendline(command.encode())
        self.terminal.sendline(MARK_EXIT)
        try:
            self.terminal.expect(EXIT, timeout)
        except pexpect.TIMEOUT:
            # Interrupting usually also discards the pending marker line, so send it again.
            self.terminal.sendintr()
            self.terminal.sendline(MARK_EXIT)
            self.terminal.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
            self.terminal.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
            raise TimeoutError(
                f"{command!r} took more than {timeout} seconds"
            ) from None
        assert self.terminal.before is not None
        return CompletedProcess(
            command, int(self.terminal.match.group(1)), self.terminal.before
        )

    @override
    def start(self, command: str) -> ShellCommand:
        directory = shlex.quote(self.execute("mktemp -d").stdout.decode().strip())
        started = self.execute(
            f"sh -c {shlex.quote(command)} > {directory}/out 2> {directory}/err < /dev/null & echo $!"
        )
        started.check_returncode()
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return ShellCommand(self, started.stdout.split()[-1].decode(), directory)

    @override
    def upload(self, local: Path, remote: str) -> None:
        # In lines short enough for the terminal.
        target = shlex.quote(remote)
        data = local.read_bytes()
        lines = [f": > {target}"] + [
            f"printf '{printf_format(data[i : i + UPLOAD_CHUNK_SIZE])}' >> {target}"
            for i in range(0, len(data), UPLOAD_CHUNK_SIZE)
        ]
        self.execute(" &&\n".join(lines)).check_returncode()

    @override
    def download(self, remote: str, local: Path) -> None:
        result = self.execute(f"cat {shlex.quote(remote)}")
        result.check_returncode()
        local.write_bytes(result.stdout)
