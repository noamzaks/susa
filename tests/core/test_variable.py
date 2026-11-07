from __future__ import annotations

import os
import subprocess
import sys

import pytest

from susa.communicators.container import ContainerCommunicator
from susa.core.communicator import HOST
from susa.core.variable import EnvironmentVariable, Variable


def test_variable() -> None:
    variable = Variable(1)
    with variable.set(2):
        assert variable.get() == 2
        with variable.set(3):
            assert variable.get() == 3
        assert variable.get() == 2
    assert variable.get() == 1


def test_variable_exception() -> None:
    variable = Variable("a")
    with pytest.raises(ValueError), variable.set("b"):
        raise ValueError
    assert variable.get() == "a"


def test_variable_default_factory() -> None:
    made: list[int] = []

    def make() -> int:
        made.append(len(made))
        return len(made)

    variable = Variable(default_factory=make)
    with variable.set(5):
        assert variable.get() == 5
    assert not made
    assert (variable.get(), variable.get()) == (1, 1)


def test_environment_variable() -> None:
    variable: EnvironmentVariable[str | None] = EnvironmentVariable(
        "SUSA_TEST_VARIABLE", "a"
    )
    assert "SUSA_TEST_VARIABLE" not in os.environ
    with variable.set("b"):
        assert variable.get() == "b"
        assert os.environ["SUSA_TEST_VARIABLE"] == '"b"'
        with variable.set(None):
            assert os.environ["SUSA_TEST_VARIABLE"] == "null"
        assert os.environ["SUSA_TEST_VARIABLE"] == '"b"'
    assert "SUSA_TEST_VARIABLE" not in os.environ
    assert variable.get() == "a"


# Processes started meanwhile start with it.
def test_environment_variable_process() -> None:
    code = "from susa.core.communicator import HOST; print(vars(HOST.get()))"
    host = ContainerCommunicator(1, ["net"])
    with HOST.set(host):
        output = subprocess.check_output([sys.executable, "-c", code], text=True)
    assert output == "{'pid': 1, 'namespaces': ['net']}\n"
