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

from susa.communicator.posix import PosixFileTransfer, printf_lines
from susa.core.communicator import AsyncCommand, AsyncCommandRunner
from susa.core.machine import Machine
from susa.core.stream import InputOutputStream, InputStream, OutputStream, PexpectStream

EXIT = re.compile(rb"SUSA-EXIT-(\d+)\n")
MARK_EXIT = b"echo SUSA-EXIT-$?"
# No line editing (which may reset the terminal's settings), job notifications, echo, output translation, bells
# (when input fills up) or prompts, so the output of commands is exactly what they wrote.
SETUP = b"set +m +o emacs +o vi; stty -echo -opost -imaxbel; PS1=''; PS2=''"
SETUP_TIMEOUT = 60
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
        self.shell.execute(
            " &&\n".join(printf_lines(data, self.path))
        ).check_returncode()

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

    @abstractmethod
    def open_stream(self) -> InputOutputStream: ...

    @override
    def create(self) -> None:
        stream = self.open_stream()
        stream.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
        if self.prelude is not None:
            self.prelude(stream)
            stream.wait_until_quiet(self.quiet_time, SETUP_TIMEOUT)
        output = PexpectStream(stream)
        deadline = time.time() + SETUP_TIMEOUT
        # Input sent before the shell is ready (e.g. while logging in) may be partly discarded, so retry, clearing
        # the line first (but not before the first attempt, since interrupting a shell that's starting may kill it).
        while True:
            # One line, since turning line editing off discards whatever it already read.
            stream.write(SETUP + b"; " + MARK_EXIT + ENTER)
            try:
                output.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
                break
            except pexpect.TIMEOUT:
                if time.time() > deadline:
                    raise TimeoutError("The shell didn't become ready") from None
                stream.write(INTERRUPT)
        stream.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
        output.buffer = b""
        self.stream, self.output = stream, output

    @override
    def destroy(self) -> None:
        assert self.stream is not None
        self.stream.write(b"exit" + ENTER)
        self.stream.close()
        self.stream, self.output = None, None

    def execute(self, command: str, timeout: float = 60) -> CompletedProcess[bytes]:
        assert self.stream is not None and self.output is not None
        self.stream.write(command.encode() + ENTER + MARK_EXIT + ENTER)
        try:
            self.output.expect(EXIT, timeout)
        except pexpect.TIMEOUT:
            # Interrupting usually also discards the pending marker line, so send it again.
            self.stream.write(INTERRUPT + MARK_EXIT + ENTER)
            self.output.expect(EXIT, SETUP_ATTEMPT_TIMEOUT)
            self.stream.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
            self.output.buffer = b""
            raise TimeoutError(
                f"{command!r} took more than {timeout} seconds"
            ) from None
        before, match = self.output.before, self.output.match
        # Sanity.
        assert before is not None and isinstance(match, re.Match)
        return CompletedProcess(command, int(match.group(1)), before)

    @override
    def start(self, command: str) -> ShellCommand:
        return ShellCommand(self, command)

    def background(self, command: str) -> str:
        started = self.execute(f"{command} & echo $!")
        started.check_returncode()
        # Interactive shells may also print the job number (e.g. "[1] 1234").
        return started.stdout.split()[-1].decode()


# A shell reached over the network: on a machine (at its IP, once it has one), or at an address (e.g. of a host SUSA
# doesn't manage).
class NetworkCommunicator(ShellCommunicator):
    def __init__(self, machine: Machine | str, prelude: Prelude | None = None) -> None:
        super().__init__(prelude)
        self.machine = machine

    @property
    def host(self) -> str:
        return self.machine if isinstance(self.machine, str) else self.machine.ip
