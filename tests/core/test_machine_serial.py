from __future__ import annotations

from susa.core.machine import CommandSerial


def test_command_serial_is_a_terminal() -> None:
    with CommandSerial(["sh", "-c", "tty; stty raw; cat"]) as serial:
        assert serial.read_until(b"\n", 5).startswith(b"/dev/pts/")
        serial.write(b"hello\n")
        assert b"hello" in serial.read_until(b"hello", 5)
