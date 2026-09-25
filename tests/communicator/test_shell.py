import random
from pathlib import Path

import pytest
from typing_extensions import override

from susa.communicator.shell import Child, Prelude, ShellCommunicator, Spawn
from susa.core.communicator import CommandResult

SHELLS = {
    "bash": ["bash", "--norc", "--noprofile", "-i"],
    "posix": ["bash", "--posix", "--norc", "--noprofile", "-i"],
}


class LocalShell(ShellCommunicator):
    def __init__(self, argv: list[str], prelude: Prelude | None = None) -> None:
        super().__init__(prelude)
        self.argv = argv

    @override
    def spawn(self) -> Child:
        return Spawn(self.argv[0], self.argv[1:])


@pytest.fixture(params=list(SHELLS))
def shell(request: pytest.FixtureRequest) -> LocalShell:
    return LocalShell(SHELLS[request.param])


def assert_gone(shell: ShellCommunicator, pattern: str) -> None:
    """Signalled processes exit asynchronously, so give them a moment."""
    shell.check(
        f"(for i in $(seq 50); do pgrep -f '^{pattern}$' > /dev/null || exit 0; sleep 0.1; done; exit 1)"
    )


def test_run(shell: LocalShell) -> None:
    with shell:
        assert shell.run("echo a; echo b >&2; exit 3") == CommandResult(
            b"a\n", b"b\n", 3
        )
        assert shell.run("printf 'x\\000\\377\\r\\n'") == CommandResult(
            b"x\x00\xff\r\n", b"", 0
        )
        assert shell.check("printf 7") == b"7"
        with pytest.raises(RuntimeError, match="failed with 3"):
            shell.check("exit 3")


def test_execute(shell: LocalShell) -> None:
    with shell:
        assert shell.execute("cd /tmp; pwd; false") == (b"/tmp\n", 1)
        assert shell.execute("pwd") == (b"/tmp\n", 0)
        with pytest.raises(TimeoutError):
            shell.execute("sleep 5", timeout=0.5)
        assert shell.execute("echo still usable") == (b"still usable\n", 0)


def test_start(shell: LocalShell) -> None:
    with shell:
        process = shell.start("echo first; echo oops >&2; sleep 1; printf last; exit 4")
        assert process.poll() is None
        assert process.stdout.read(timeout=5) == b"first\n"
        assert process.stderr.read(timeout=5) == b"oops\n"
        assert process.stdout.read() == b""
        assert process.wait() == 4
        assert process.poll() == 4
        assert process.stdout.read() == b"last"


def test_start_read_size(shell: LocalShell) -> None:
    with shell:
        process = shell.start("printf 0123456789")
        process.wait()
        assert process.stdout.read(4) == b"0123"
        assert process.stdout.read_until(b"9", timeout=5) == b"456789"


def test_start_kill(shell: LocalShell) -> None:
    with shell:
        process = shell.start("exec sleep 3601")
        with pytest.raises(TimeoutError):
            process.wait(timeout=0.5)
        process.kill()
        assert process.wait(timeout=5) == 128 + 15
        assert_gone(shell, "sleep 3601")


def test_run_timeout_kills(shell: LocalShell) -> None:
    with shell:
        with pytest.raises(TimeoutError):
            shell.run("exec sleep 3602", timeout=0.5)
        assert_gone(shell, "sleep 3602")


def test_prelude() -> None:
    def prelude(child: Child) -> None:
        child.sendline(b"cd /tmp")

    with LocalShell(SHELLS["bash"], prelude) as shell:
        assert shell.execute("pwd") == (b"/tmp\n", 0)


def test_transfer(shell: LocalShell, tmp_path: Path) -> None:
    data = random.randbytes(5000)
    (tmp_path / "up").write_bytes(data)
    with shell:
        shell.upload(tmp_path / "up", str(tmp_path / "remote"))
        shell.download(str(tmp_path / "remote"), tmp_path / "down")
    assert (tmp_path / "remote").read_bytes() == data
    assert (tmp_path / "down").read_bytes() == data
