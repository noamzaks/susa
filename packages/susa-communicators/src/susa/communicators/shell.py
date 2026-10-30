from __future__ import annotations

import contextlib
import logging
import re
import time
from abc import abstractmethod
from collections.abc import Callable
from subprocess import CompletedProcess
from typing import TYPE_CHECKING, TypeAlias

import pexpect
from pexpect.spawnbase import SpawnBase
from typing_extensions import override

from susa.core.communicator import CommandRunner
from susa.core.stream import InputOutputStream, OutputStream
from susa.utilities.generic import Deadline

Prelude: TypeAlias = Callable[[InputOutputStream], None]


class ShellCommunicator(CommandRunner):
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
    ENTER = b"\r"
    INTERRUPT = b"\x03"

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
        deadline = Deadline(ShellCommunicator.CONNECT_TIMEOUT)
        while True:
            logging.debug("Connecting to the shell")
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
                logging.debug("The shell's connection closed")
                self.stream.close()
                if deadline.passed():
                    raise
                time.sleep(ShellCommunicator.RECONNECT_INTERVAL)

    def attach(self, interrupt: bool) -> bool:
        assert self.stream is not None
        if interrupt:
            self.stream.write(ShellCommunicator.INTERRUPT)
        try:
            self.stream.wait_until_quiet(
                self.quiet_time, ShellCommunicator.SETUP_TIMEOUT
            )
            if self.prelude is not None:
                self.prelude(self.stream)
                self.stream.wait_until_quiet(
                    self.quiet_time, ShellCommunicator.SETUP_TIMEOUT
                )
            self.output = PexpectStream(self.stream)
            # Programs the shell starts with may discard part of what's typed (e.g. FreeBSD's resizewin), and what's
            # left of the setup could start one (e.g. `vi`), unlike what's left of an exit marker.
            self.stream.write(ShellCommunicator.MARK_EXIT + ShellCommunicator.ENTER)
            if not self.expect_exit(ShellCommunicator.SETUP_ATTEMPT_TIMEOUT):
                return False
            # One line, since turning line editing off discards whatever it already read.
            self.stream.write(
                ShellCommunicator.SETUP
                + b"; "
                + ShellCommunicator.MARK_EXIT
                + ShellCommunicator.ENTER
            )
            if not self.expect_exit(ShellCommunicator.SETUP_ATTEMPT_TIMEOUT):
                return False
            self.stream.wait_until_quiet(
                ShellCommunicator.RECOVERY_QUIET_TIME, ShellCommunicator.SETUP_TIMEOUT
            )
            self.output.buffer = b""
            # Part of the setup may have been discarded with the marker still sent.
            probe = self.run(
                f"echo {ShellCommunicator.READY}",
                ShellCommunicator.SETUP_ATTEMPT_TIMEOUT,
            )
        except TimeoutError:
            return False
        return probe.stdout == f"{ShellCommunicator.READY}\n".encode()

    @override
    def destroy(self) -> None:
        assert self.stream is not None
        # Its client may be gone already (e.g. Ctrl-C reaches it too).
        with contextlib.suppress(BrokenPipeError):
            self.stream.write(b"exit" + ShellCommunicator.ENTER)
        self.stream.close()
        self.stream, self.output = None, None

    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]:
        assert self.stream is not None and self.output is not None
        logging.debug("Running %.200r in the shell", command)
        self.stream.write(
            command.encode()
            + ShellCommunicator.ENTER
            + ShellCommunicator.MARK_EXIT
            + ShellCommunicator.ENTER
        )
        if not self.expect_exit(timeout):
            # Interrupting usually also discards the pending marker line, so send it again.
            self.stream.write(
                ShellCommunicator.INTERRUPT
                + ShellCommunicator.MARK_EXIT
                + ShellCommunicator.ENTER
            )
            self.expect_exit(ShellCommunicator.SETUP_ATTEMPT_TIMEOUT)
            self.stream.wait_until_quiet(
                ShellCommunicator.RECOVERY_QUIET_TIME, ShellCommunicator.SETUP_TIMEOUT
            )
            self.output.buffer = b""
            raise TimeoutError(f"{command!r} took more than {timeout} seconds")
        before, match = self.output.before, self.output.match
        # Sanity.
        assert before is not None and isinstance(match, re.Match)
        exit_code = int(match.group(1))
        logging.debug("It exited with %d, writing %.1000r", exit_code, before)
        return CompletedProcess(command, exit_code, before)

    def expect_exit(self, timeout: float | None) -> bool:
        assert self.output is not None
        return (
            self.output.expect([ShellCommunicator.EXIT, pexpect.TIMEOUT], timeout) == 0
        )


# It's only generic in its stubs.
if TYPE_CHECKING:
    BytesSpawnBase = SpawnBase[bytes]
else:
    BytesSpawnBase = SpawnBase


class PexpectStream(BytesSpawnBase):
    def __init__(self, stream: OutputStream) -> None:
        super().__init__()
        self.stream = stream

    @override
    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> bytes:
        return self.stream.read(size, timeout)
