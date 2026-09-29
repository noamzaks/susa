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
from susa.core.stream import InputStream, OutputStream

EXIT = re.compile(rb"SUSA-EXIT-(\d+)\n")
MARK_EXIT = b"echo SUSA-EXIT-$?"
# No line editing (which may reset the terminal's settings), job notifications, echo, output translation or
# prompts, so the output of commands is exactly what they wrote.
SETUP = b"set +m +o emacs +o vi; stty -echo -opost; PS1=''; PS2=''"
SETUP_TIMEOUT = 60
SETUP_ATTEMPT_TIMEOUT = 10
RECOVERY_QUIET_TIME = 1
POLL_INTERVAL = 0.2
PRINTF_CHUNK_SIZE = 512

Prelude: TypeAlias = Callable[[Terminal], None]


def login(password: str, username: str | None = None, quiet_time: float = 3) -> Prelude:
    lines = ([username.encode()] if username is not None else []) + [password.encode()]

    def prelude(terminal: Terminal) -> None:
        for line in lines:
            # Input sent before the login program prompts is usually discarded.
            terminal.wait_until_quiet(quiet_time, SETUP_TIMEOUT)
            terminal.sendline(line)

    return prelude


def printf_lines(data: bytes, target: str) -> list[str]:
    # Short enough lines for the terminal, with nothing but POSIX `printf`.
    return [
        "printf '"
        + "".join(
            chr(b) if chr(b).isalnum() and b < 128 else f"\\{b:03o}"
            for b in data[i : i + PRINTF_CHUNK_SIZE]
        )
        + f"' >> {target}"
        for i in range(0, len(data), PRINTF_CHUNK_SIZE)
    ]


class ShellInputStream(InputStream):
    def __init__(self, shell: ShellCommunicator, path: str) -> None:
        self.shell = shell
        self.path = path
        # Keeps the FIFO open (so the command doesn't see its end) until it's closed.
        self.holder: str | None = shell.background(f"sleep 2147483647 > {path}")

    @override
    def write(self, data: bytes) -> None:
        self.shell.execute(
            " &&\n".join(printf_lines(data, self.path))
        ).check_returncode()

    @override
    def close(self) -> None:
        if self.holder is not None:
            self.shell.execute(f"kill {self.holder}; wait {self.holder}")
            self.holder = None


class ShellOutputStream(OutputStream):
    def __init__(self, command: ShellCommand, path: str) -> None:
        self.command = command
        self.path = path
        self.offset = 0

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.time() + timeout
        head = "" if size is None else f" | head -c {size}"
        while True:
            finished = self.command.poll() is not None
            data = self.command.shell.execute(
                f"tail -c +{self.offset + 1} {self.path}{head}"
            ).stdout
            if data:
                self.offset += len(data)
                return data
            if finished:
                raise EOFError
            if time.time() >= deadline:
                return b""
            time.sleep(POLL_INTERVAL)


class ShellCommand(AsyncCommand):
    def __init__(self, shell: ShellCommunicator, command: str) -> None:
        self.shell = shell
        directory = shlex.quote(shell.execute("mktemp -d").stdout.decode().strip())
        shell.execute(f"mkfifo {directory}/in").check_returncode()
        self.pid = shell.background(
            f"sh -c {shlex.quote(command)} < {directory}/in > {directory}/out 2> {directory}/err"
        )
        self.exit_code: int | None = None
        self._stdin = ShellInputStream(shell, f"{directory}/in")
        self._stdout = ShellOutputStream(self, f"{directory}/out")
        self._stderr = ShellOutputStream(self, f"{directory}/err")

    @property
    @override
    def stdin(self) -> InputStream:
        return self._stdin

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
            self._stdin.close()
        return self.exit_code

    @override
    def kill(self) -> None:
        self.shell.execute(f"kill {self.pid}")


class ShellCommunicator(AsyncCommandRunner, FileTransferrer):
    def __init__(self, prelude: Prelude | None = None, quiet_time: float = 3) -> None:
        self.prelude = prelude
        # Long enough for whatever runs at login (which may silently wait for the terminal) to be done.
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

    def background(self, command: str) -> str:
        started = self.execute(f"{command} & echo $!")
        started.check_returncode()
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return started.stdout.split()[-1].decode()

    @override
    def start(self, command: str) -> ShellCommand:
        return ShellCommand(self, command)

    @override
    def upload(self, local: Path, remote: str) -> None:
        target = shlex.quote(remote)
        lines = [f": > {target}", *printf_lines(local.read_bytes(), target)]
        self.execute(" &&\n".join(lines)).check_returncode()

    @override
    def download(self, remote: str, local: Path) -> None:
        result = self.execute(f"cat {shlex.quote(remote)}")
        result.check_returncode()
        local.write_bytes(result.stdout)
