from __future__ import annotations

import contextlib
import logging
import re
import time
from abc import abstractmethod
from collections.abc import Callable
from subprocess import CompletedProcess
from typing import TypeAlias

from typing_extensions import override

from susa.core.communicator import CommandRunner
from susa.core.stream import InputOutputStream
from susa.utilities.generic import Deadline

Prelude: TypeAlias = Callable[[InputOutputStream], None]


class ShellCommunicator(CommandRunner):
    EXIT = re.compile(rb"SUSA-EXIT-(\d+)\r?\n")
    MARK_EXIT = b"echo SUSA-EXIT-$?"
    READY = "SUSA-READY"
    HUNG_UP = b"SUSA-HUNG-UP\n"
    HANG_UP = b"echo SUSA-HUNG-UP; kill -HUP 0"
    SETUP = b"set +m +o emacs +o vi; stty -echo -opost -imaxbel; PS1=''; PS2=''; PROMPT_COMMAND=''"
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

    @abstractmethod
    def open_stream(self) -> InputOutputStream: ...

    @override
    def create(self) -> None:
        deadline = Deadline(ShellCommunicator.CONNECT_TIMEOUT)
        while True:
            logging.debug("Connecting to the shell")
            self.stream = self.open_stream()
            try:
                interrupt = False
                while not self.attach(interrupt):
                    deadline.test("The shell didn't become ready")
                    interrupt = True
                return
            except (EOFError, BrokenPipeError):
                logging.debug("The shell's connection closed")
                self.stream.close()
                if deadline.passed():
                    raise
                time.sleep(ShellCommunicator.RECONNECT_INTERVAL)
            except BaseException:
                self.stream.close()
                self.stream = None
                raise

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
            self.stream.write(ShellCommunicator.MARK_EXIT + ShellCommunicator.ENTER)
            self.stream.read_until(
                ShellCommunicator.EXIT, ShellCommunicator.SETUP_ATTEMPT_TIMEOUT
            )
            self.stream.write(
                ShellCommunicator.SETUP
                + b"; "
                + ShellCommunicator.MARK_EXIT
                + ShellCommunicator.ENTER
            )
            self.stream.read_until(
                ShellCommunicator.EXIT, ShellCommunicator.SETUP_ATTEMPT_TIMEOUT
            )
            self.stream.wait_until_quiet(
                ShellCommunicator.RECOVERY_QUIET_TIME, ShellCommunicator.SETUP_TIMEOUT
            )
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
        try:
            with contextlib.suppress(BrokenPipeError):
                self.stream.write(ShellCommunicator.HANG_UP + ShellCommunicator.ENTER)
                self.stream.read_until(
                    ShellCommunicator.HUNG_UP, ShellCommunicator.SETUP_ATTEMPT_TIMEOUT
                )
        finally:
            self.stream.close()
            self.stream = None

    @override
    def run(
        self, command: str, timeout: float | None = None
    ) -> CompletedProcess[bytes]:
        assert self.stream is not None
        logging.debug("Running %.200r in the shell", command)
        self.stream.write(
            command.encode()
            + ShellCommunicator.ENTER
            + ShellCommunicator.MARK_EXIT
            + ShellCommunicator.ENTER
        )
        try:
            output = self.stream.read_until(ShellCommunicator.EXIT, timeout)
        except TimeoutError:
            self.stream.write(
                ShellCommunicator.INTERRUPT
                + ShellCommunicator.MARK_EXIT
                + ShellCommunicator.ENTER
            )
            with contextlib.suppress(TimeoutError):
                self.stream.read_until(
                    ShellCommunicator.EXIT, ShellCommunicator.SETUP_ATTEMPT_TIMEOUT
                )
            self.stream.wait_until_quiet(
                ShellCommunicator.RECOVERY_QUIET_TIME, ShellCommunicator.SETUP_TIMEOUT
            )
            raise TimeoutError(
                f"{command!r} took more than {timeout} seconds"
            ) from None
        match = ShellCommunicator.EXIT.search(output)
        assert match is not None
        stdout, exit_code = output[: match.start()], int(match[1])
        logging.debug("It exited with %d, writing %.1000r", exit_code, stdout)
        return CompletedProcess(command, exit_code, stdout)
