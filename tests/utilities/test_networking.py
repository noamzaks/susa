import re
import subprocess

import pytest

from susa.utilities.networking import ping, random_mac


def test_ping() -> None:
    single = ping("127.0.0.1")
    assert isinstance(single, float)

    multiple = ping("127.0.0.1", 3, interval=1)
    assert len(multiple) == 3
    assert all(isinstance(time, float) for time in multiple)

    # 10.255.255.1 is a non-routable address, so no replies should come back.
    assert ping("10.255.255.1", 2) == [None, None]

    with pytest.raises(subprocess.CalledProcessError):
        ping("nonexistent.invalid")


def test_random_mac() -> None:
    mac = random_mac()
    assert re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac)


@pytest.mark.parametrize("prefix", ("52", "52:54:00", "52:54:00:12:34"))
def test_random_mac_prefix(prefix: str) -> None:
    mac = random_mac(prefix)
    assert mac.startswith(prefix + ":")
    assert re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac)


def test_random_mac_full_prefix() -> None:
    assert random_mac("52:54:00:12:34:56") == "52:54:00:12:34:56"
