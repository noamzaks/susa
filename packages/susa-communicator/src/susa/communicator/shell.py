from __future__ import annotations

import re
import time
from abc import abstractmethod
from collections.abc import Callable
from subprocess import CompletedProcess
from typing import TypeAlias

import pexpect
from pexpect.spawnbase import SpawnBase
from typing_extensions import override

from susa.communicator.login import ENTER
from susa.core.communicator import CommandRunner
from susa.core.stream import InputOutputStream, OutputStream
from susa.utilities.generic import Deadline

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

INTERRUPT = b"\x03"

Prelude: TypeAlias = Callable[[InputOutputStream], None]


class ShellCommunicator(CommandRunner):
    def __init__(self, prelude: Prelude | None = None, quiet_time: float = 3) -> None:
        self.prelude = prelude
        self.quiet_time = quiet_time
        self.stream: InputOutputStream | None = None
        self.output: PexpectStream | None = None

    @abstractmethod
    def open_stream(self) -> InputOutputStream: ...

    # The machine may still be booting.
    @override
    def create(self) -> None:
        deadline = Deadline(CONNECT_TIMEOUT)
        while True:
            self.stream = self.open_stream()
            try:
                # Interrupting a client or a shell that's starting may kill it.
                interrupt = False
                while not self.attach(interrupt):
                    if deadline.passed():
                        raise TimeoutError("The shell didn't become ready")
                    interrupt = True
                return
            except EOFError:
                self.stream.close()
                if deadline.passed():
                    raise
                time.sleep(RECONNECT_INTERVAL)

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
            # left of the setup could start one (e.g. `vi`), unlike what's left of an exit marker.
            self.stream.write(MARK_EXIT + ENTER)
            if not self.expect_exit(SETUP_ATTEMPT_TIMEOUT):
                return False
            # One line, since turning line editing off discards whatever it already read.
            self.stream.write(SETUP + b"; " + MARK_EXIT + ENTER)
            if not self.expect_exit(SETUP_ATTEMPT_TIMEOUT):
                return False
            self.stream.wait_until_quiet(RECOVERY_QUIET_TIME, SETUP_TIMEOUT)
            self.output.buffer = b""
            # Part of the setup may have been discarded with the marker still sent.
            probe = self.run(f"echo {READY}", SETUP_ATTEMPT_TIMEOUT)
        except TimeoutError:
            return False
        return probe.stdout == f"{READY}\n".encode()

    @override
    def destroy(self) -> None:
        assert self.stream is not None
        self.stream.write(b"exit" + ENTER)
        self.stream.close()
        self.stream, self.output = None, None

    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]:
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

    def expect_exit(self, timeout: float | None) -> bool:
        assert self.output is not None
        return self.output.expect([EXIT, pexpect.TIMEOUT], timeout) == 0


class PexpectStream(SpawnBase):  # type: ignore
    def __init__(self, stream: OutputStream) -> None:
        super().__init__()
        self.stream = stream

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        return self.stream.read(size, timeout)
