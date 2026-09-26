from __future__ import annotations

import random
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest
from typing_extensions import override

from susa.communicator.shell import Prelude, ShellCommunicator
from susa.communicator.terminal import ProcessTerminal, Terminal

SHELLS = {
    "bash": ["bash", "--norc", "--noprofile", "-i"],
    "posix": ["bash", "--posix", "--norc", "--noprofile", "-i"],
}


class LocalShell(ShellCommunicator):
    def __init__(self, argv: list[str], prelude: Prelude | None = None) -> None:
        super().__init__(prelude, quiet_time=1)
        self.argv = argv

    @override
    def open_terminal(self) -> Terminal:
        return ProcessTerminal(*self.argv)


@pytest.fixture(params=list(SHELLS))
def shell(request: pytest.FixtureRequest) -> LocalShell:
    return LocalShell(SHELLS[request.param])


def result(result: CompletedProcess[bytes]) -> tuple[int, bytes, bytes | None]:
    return result.returncode, result.stdout, result.stderr


def assert_gone(shell: ShellCommunicator, pattern: str) -> None:
    """Signalled processes exit asynchronously, so give them a moment."""
    shell.check(
        f"(for i in $(seq 50); do pgrep -f '^{pattern}$' > /dev/null || exit 0; sleep 0.1; done; exit 1)"
    )


def test_run(shell: LocalShell) -> None:
    with shell:
        assert result(shell.run("echo a; echo b >&2; exit 3")) == (3, b"a\n", b"b\n")
        assert result(shell.run("printf 'x\\000\\377\\r\\n'")) == (
            0,
            b"x\x00\xff\r\n",
            b"",
        )
        assert shell.check("printf 7") == b"7"
        with pytest.raises(CalledProcessError) as error:
            shell.check("echo oops >&2; exit 3")
        assert (error.value.returncode, error.value.stderr) == (3, b"oops\n")


def test_execute(shell: LocalShell) -> None:
    with shell:
        assert result(shell.execute("cd /tmp; pwd; echo e >&2; false")) == (
            1,
            b"/tmp\ne\n",
            None,
        )
        assert shell.execute("pwd").stdout == b"/tmp\n"
        with pytest.raises(TimeoutError):
            shell.execute("sleep 5", timeout=0.5)
        assert shell.execute("echo still usable").stdout == b"still usable\n"


def test_start(shell: LocalShell) -> None:
    with shell:
        command = shell.start("echo first; echo oops >&2; sleep 1; printf last; exit 4")
        assert command.poll() is None
        assert command.stdout.read(timeout=5) == b"first\n"
        assert command.stderr.read(timeout=5) == b"oops\n"
        assert command.stdout.read() == b""
        assert command.wait() == 4
        assert command.poll() == 4
        assert command.stdout.read() == b"last"


def test_start_read_size(shell: LocalShell) -> None:
    with shell:
        command = shell.start("printf 0123456789")
        command.wait()
        assert command.stdout.read(4) == b"0123"
        assert command.stdout.read_until(b"9", timeout=5) == b"456789"


def test_start_kill(shell: LocalShell) -> None:
    with shell:
        command = shell.start("exec sleep 3601")
        with pytest.raises(TimeoutError):
            command.wait(timeout=0.5)
        command.kill()
        assert command.wait(timeout=5) == 128 + 15
        assert_gone(shell, "sleep 3601")


def test_run_timeout_kills(shell: LocalShell) -> None:
    with shell:
        with pytest.raises(TimeoutError):
            shell.run("exec sleep 3602", timeout=0.5)
        assert_gone(shell, "sleep 3602")


def test_prelude() -> None:
    def prelude(terminal: Terminal) -> None:
        terminal.sendline(b"cd /tmp")

    with LocalShell(SHELLS["bash"], prelude) as shell:
        assert shell.execute("pwd").stdout == b"/tmp\n"


def test_transfer(shell: LocalShell, tmp_path: Path) -> None:
    data = random.randbytes(5000)
    (tmp_path / "up").write_bytes(data)
    with shell:
        shell.upload(tmp_path / "up", str(tmp_path / "remote"))
        shell.download(str(tmp_path / "remote"), tmp_path / "down")
    assert (tmp_path / "remote").read_bytes() == data
    assert (tmp_path / "down").read_bytes() == data
