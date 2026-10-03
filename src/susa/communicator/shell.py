from __future__ import annotations

import re
import shlex
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from subprocess import CompletedProcess
from typing import TypeAlias

import pexpect
from typing_extensions import override

from susa.communicator.posix import PosixFileTransfer, printf_command
from susa.core.communicator import AsyncCommand, AsyncCommandRunner
from susa.core.stream import InputOutputStream, InputStream, OutputStream, PexpectStream

# Before the setup turns output translation off, newlines come out as "\r\n".
EXIT = re.compile(rb"SUSA-EXIT-(\d+)\r?\n")
MARK_EXIT = b"echo SUSA-EXIT-$?"
READY = "SUSA-READY"
# No line editing (which may reset the terminal's settings), job notifications, echo, output translation, bells
# (when input fills up) or prompts, so the output of commands is exactly what they wrote.
SETUP = b"set +m +o emacs +o vi; stty -echo -opost -imaxbel; PS1=''; PS2=''"
CONNECT_TIMEOUT = 600
SETUP_TIMEOUT = 60
RECONNECT_INTERVAL = 1
SETUP_ATTEMPT_TIMEOUT = 10
RECOVERY_QUIET_TIME = 1
POLL_INTERVAL = 0.2

ENTER = b"\r"
INTERRUPT = b"\x03"

Prelude: TypeAlias = Callable[[InputOutputStream], None]


# A prelude that logs in: the username (if any), then the password, each once the terminal is quiet (since input sent
# before a login program prompts is usually discarded).
@dataclass(frozen=True)
class Login:
    password: str
    username: str | None = None
    quiet_time: float = 3

    def __call__(self, stream: InputOutputStream) -> None:
        for line in [self.username, self.password]:
            if line is None:
                continue
            stream.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
            stream.write(line.encode() + ENTER)


class ShellInputStream(InputStream):
    def __init__(self, shell: ShellCommunicator, path: str) -> None:
        self.shell = shell
        self.path = path
        # Keeps the FIFO open (so the command doesn't see its end) until it's closed.
        self.holder: str | None = shell.background(f"sleep 2147483647 > {path}")

    @override
    def write(self, data: bytes) -> None:
        self.shell.posix(printf_command(data, self.path))

    @override
    def close(self) -> None:
        if self.holder is None:
            return
        self.shell.execute(f"kill {self.holder}; wait {self.holder}")
        self.holder = None


class ShellOutputStream(OutputStream):
    def __init__(self, command: ShellCommand, path: str) -> None:
        self.command = command
        self.path = path
        self.offset = 0

    @override
    def read(self, size: int | None = None, timeout: float = 0) -> bytes:
        deadline = time.monotonic() + timeout
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
            if time.monotonic() >= deadline:
                return b""
            time.sleep(POLL_INTERVAL)


class ShellCommand(AsyncCommand):
    def __init__(self, shell: ShellCommunicator, command: str) -> None:
        self.shell = shell
        assert shell.directory is not None
        template = shlex.quote(f"{shell.directory}/command.XXXXXX")
        directory = shlex.quote(shell.posix(f"mktemp -d {template}").decode().strip())
        shell.posix(f"mkfifo {directory}/in")
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
        if self.exit_code is not None:
            return self.exit_code
        self.exit_code = self.shell.execute(f"wait {self.pid}", timeout).returncode
        self._stdin.close()
        return self.exit_code

    @override
    def kill(self) -> None:
        self.shell.execute(f"kill {self.pid}")


class ShellCommunicator(PosixFileTransfer, AsyncCommandRunner):
    def __init__(self, prelude: Prelude | None = None, quiet_time: float = 3) -> None:
        self.prelude = prelude
        # Long enough for whatever runs at login (which may silently wait for input) to be done.
        self.quiet_time = quiet_time
        self.stream: InputOutputStream | None = None
        self.output: PexpectStream | None = None
        self.directory: str | None = None

    @abstractmethod
    def open_stream(self) -> InputOutputStream: ...

    # The machine may still be booting (e.g. refusing connections, or not at its login prompt yet), so this tries again
    # until the shell is ready, connecting again if the connection ended.
    @override
    def create(self) -> None:
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while True:
            self.stream = self.open_stream()
            try:
                # Interrupting clears what earlier attempts left (e.g. a half-typed login), but not on a new connection,
                # since interrupting a client or a shell that's starting may kill it.
                interrupt = False
                while not self.attach(interrupt):
                    check_deadline(deadline)
                    interrupt = True
                break
            except EOFError:
                self.stream.close()
                check_deadline(deadline)
                time.sleep(RECONNECT_INTERVAL)
        self.directory = self.posix("mktemp -d").decode().strip()

    # Whether logging in (with the prelude) and setting up the shell worked.
    def attach(self, interrupt: bool) -> bool:
        assert self.stream is not None
        if interrupt:
            self.stream.write(INTERRUPT)
        try:
            self.stream.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
            if self.prelude is not None:
                self.prelude(self.stream)
                self.stream.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
            self.output = PexpectStream(self.stream)
            # Programs the shell starts with may discard part of what's typed (e.g. FreeBSD's resizewin), and what's
            # left of the setup could start one (e.g. `vi`). What's left of an exit marker can't, so the setup waits
            # for one to show the shell's reading.
            self.stream.write(MARK_EXIT + ENTER)
            if not self.expect_exit(SETUP_ATTEMPT_TIMEOUT):
                return False
            # One line, since turning line editing off discards whatever it already read.
            self.stream.write(SETUP + b"; " + MARK_EXIT + ENTER)
            if not self.expect_exit(SETUP_ATTEMPT_TIMEOUT):
                return False
            self.stream.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
            self.output.buffer = b""
            # Part of the setup may have been discarded (e.g. by a program the shell was still running) with the marker
            # still sent, so the output's checked to be exactly what a command writes.
            probe = self.execute(f"echo {READY}", SETUP_ATTEMPT_TIMEOUT)
        except TimeoutError:
            return False
        return probe.stdout == f"{READY}\n".encode()

    @override
    def destroy(self) -> None:
        assert self.stream is not None and self.directory is not None
        self.execute(f"rm -r {shlex.quote(self.directory)}")
        self.stream.write(b"exit" + ENTER)
        self.stream.close()
        self.stream, self.output, self.directory = None, None, None

    @override
    def execute(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]:
        assert self.stream is not None and self.output is not None
        self.stream.write(command.encode() + ENTER + MARK_EXIT + ENTER)
        if not self.expect_exit(timeout):
            # Interrupting usually also discards the pending marker line, so send it again.
            self.stream.write(INTERRUPT + MARK_EXIT + ENTER)
            self.expect_exit(SETUP_ATTEMPT_TIMEOUT)
            self.stream.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
            self.output.buffer = b""
            raise TimeoutError(f"{command!r} took more than {timeout} seconds")
        before, match = self.output.before, self.output.match
        # Sanity.
        assert before is not None and isinstance(match, re.Match)
        return CompletedProcess(command, int(match.group(1)), before)

    # Whether the exit marker arrived in time.
    def expect_exit(self, timeout: float) -> bool:
        assert self.output is not None
        return self.output.expect([EXIT, pexpect.TIMEOUT], timeout) == 0

    @override
    def start(self, command: str) -> ShellCommand:
        return ShellCommand(self, command)

    def background(self, command: str) -> str:
        started = self.execute(f"{command} & echo $!")
        started.check_returncode()
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return started.stdout.split()[-1].decode()


def check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise TimeoutError("The shell didn't become ready")
