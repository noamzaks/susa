from __future__ import annotations

import json
import shlex
import sys

from typing_extensions import override

from susa.communicators.login import Login
from susa.communicators.shell import ShellCommunicator
from susa.core.machine import SerialAccessible
from susa.core.serializable import JSON, Serializable, deserialize, serialize
from susa.core.stream import InputOutputStream
from susa.utilities.generic import Guard


class SerialCommunicator(ShellCommunicator, Serializable):
    DESTROY = (
        "import json, sys\n"
        "from susa.core.serializable import deserialize\n"
        "with deserialize(json.loads(sys.argv[1])):\n"
        "    pass\n"
    )

    def __init__(self, machine: SerialAccessible, login: Login | None = None) -> None:
        super().__init__(login)
        self.machine = machine
        self.login = login

    @override
    def create(self) -> None:
        super().create()
        state = json.dumps(serialize(self))
        command = [sys.executable, "-c", SerialCommunicator.DESTROY, state]
        self.guard = Guard(f"{shlex.join(command)} > /dev/null 2>&1")

    @override
    def destroy(self) -> None:
        super().destroy()
        self.guard.cancel()

    @override
    def open_stream(self) -> InputOutputStream:
        serial = self.machine.serial()
        serial.create()
        return serial

    @override
    def __getstate__(self) -> JSON:
        assert isinstance(self.machine, Serializable)
        login = None if self.login is None else serialize(self.login)
        return {"machine": serialize(self.machine), "login": login}

    @override
    def __setstate__(self, state: JSON) -> None:
        assert isinstance(state, dict)
        machine = deserialize(state["machine"])
        login = None if state["login"] is None else deserialize(state["login"])
        assert isinstance(machine, SerialAccessible)
        assert login is None or isinstance(login, Login)
        SerialCommunicator.__init__(self, machine, login)
